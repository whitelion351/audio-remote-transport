import pyaudio
import audioread
import socket
from threading import Thread
import argparse
import time


class AudioServer:
    # noinspection SpellCheckingInspection
    def __init__(self, filename=None, chunk=2048, audio_format=pyaudio.paInt16, channels=1, rate=44100,
                 bind_address="0.0.0.0", bind_port=1060, audio_buffer_size=96, buffer_size_increment=6,
                 buffer_optimize_time=10, use_compression=0, config_filename="AudioServer_devices.cfg",
                 configure_devices=False, input_device_index=None, output_device_index=None):
        # constants
        self.CHUNK = chunk             # samples per frame
        self.FORMAT = audio_format     # audio format (bytes per sample?)
        self.CHANNELS = channels       # single channel for microphone
        self.RATE = rate               # samples per second
        self.wave_data = None
        self.filename = filename
        self.file_finished = False
        self.host_api_index = None
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        self.need_to_configure = False
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.bind((bind_address, bind_port))
        self.connection.listen(5)
        self.clients = {}
        self.threads = {}
        self.buffer_size = audio_buffer_size
        self.buffer_min_size = audio_buffer_size
        self.buffer_max_size = audio_buffer_size * 2
        self.buffer_size_increment = buffer_size_increment
        self.buffer_optimize_time = buffer_optimize_time * 60
        self.audio_buffer = []
        self.buffer_id = -1
        self.highest_buffer_pos = 1
        self.use_compression = use_compression
        print("audio server running on {}:{}".format(bind_address, bind_port))

        # parse command line arguments
        parser = argparse.ArgumentParser(description="Server portion of audio transport")
        parser.add_argument("--configure_devices", default=0, type=int, choices=[0, 1],
                            help="Choose devices on program startup")
        args = parser.parse_args()
        config_arg = args.configure_devices
        if config_arg == 1 or configure_devices is True:
            self.need_to_configure = True

        if self.filename is None:
            # read config file and create audio streams
            live_audio = pyaudio.PyAudio()
            if self.need_to_configure:
                self.configure_this_instance(live_audio)
            else:
                try:
                    with open(config_filename, "r") as file:
                        line_index = 1
                        for line in file:
                            splits = line.split(sep=":")
                            if len(splits) != 2:
                                print("config file has issues on line", line_index)
                                print(line)
                                break
                            else:
                                key = splits[0]
                                value = splits[1]
                                if key == "input_device_index" and self.input_device_index is None:
                                    self.input_device_index = int(value)
                                elif key == "output_device_index" and self.output_device_index is None:
                                    self.output_device_index = int(value)
                            line_index += 1
                        else:
                            print("loaded config file")
                except IOError:
                    print("no config file found. Please choose API and devices to use")
                    self.configure_this_instance(live_audio)
            self.live_stream = live_audio.open(

                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                output=False,
                frames_per_buffer=self.CHUNK,
                input_device_index=self.input_device_index,
                output_device_index=self.input_device_index
             )
        else:
            self.file_stream = []
            with audioread.audio_open(self.filename) as f:
                self.CHANNELS = f.channels
                self.RATE = f.samplerate
                print("using file {} channels={}, samplerate={}, duration={} second(s)".format(
                    self.filename, f.channels, f.samplerate, round(f.duration, 1))
                )
                for buf in f:
                    self.file_stream.append(buf)
            self.file_data = self.file_data_reader()

        print('stream started')

    def configure_this_instance(self, instance):
        print("Listing available APIs")
        host_api_count = instance.get_host_api_count()
        infos = []
        for i in range(host_api_count):
            info = instance.get_host_api_info_by_index(i)
            print(i+1, ") ", info, sep="")
            infos.append(info)
        if len(infos) < 1:
            print("No APIs available. Configure can not continue. Hopefully the defaults work for you")
            return
        user_choice = input("Choose api: ")
        user_choice = int(user_choice) - 1
        host_api_info = infos[user_choice]
        host_api_index = host_api_info["index"]
        print("using host api:", host_api_info["name"])

        print("Listing devices available to the API")
        infos = []
        for i in range(instance.get_device_count()):
            info = instance.get_device_info_by_index(i)
            if info["hostApi"] == host_api_index:
                print("{}) name: {}, inputs: {}, outputs: {}, defaultRate: {}, deviceIndex: {}".format(
                    i+1, info["name"], info["maxInputChannels"], info["maxOutputChannels"],
                    info["defaultSampleRate"], info["index"]
                ))
                infos.append(info)
        if len(infos) < 1:
            print("No devices available for this API. Configure can not continue. Hopefully the defaults work for you")
            return
        user_choice = input("Choose input device: ")
        user_choice = int(user_choice) - 1
        input_device_info = infos[user_choice]
        input_device_index = input_device_info["index"]
        print("using {} for input".format(input_device_info["name"]))
        user_choice = input("Choose output device: ")
        user_choice = int(user_choice) - 1
        output_device_info = infos[user_choice]
        output_device_index = output_device_info["index"]
        print("using {} for output".format(input_device_info["name"]))
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        with open("config.cfg", "w") as file:
            file.write("input_device_index:" + str(self.input_device_index) + "\n")
            file.write("output_device_index:" + str(self.output_device_index) + "\n")
        return

    def wait_for_connection(self):
        if "rolling_buffer" not in self.threads.keys():
            print("starting server buffer thread")
            self.begin_rolling_buffer()
        clientsocket, address = self.connection.accept()
        clientsocket.settimeout(5)
        try:
            msg = clientsocket.recv(self.CHUNK)
            decodedmsg = msg.decode("utf-8").split(sep=",")
            print("connection received from {}".format(address))
            if decodedmsg[0] == "AudioClient" and len(decodedmsg) > 1:
                print("type is {} with buffer size {}. sending audio parameters".format(decodedmsg[0], decodedmsg[1]))
                params = "{},{},{}".format(self.RATE, self.CHUNK, self.use_compression)
                clientsocket.send(bytes(params, "utf-8"))
                msg = clientsocket.recv(self.CHUNK)
                if msg.decode("utf-8") == "ok":
                    print("creating client thread {}".format(address[0]))
                    self.clients[address[0]] = clientsocket
                    thread = Thread(target=self.send_audio_loop, name=address[0],
                                    daemon=True, args=(clientsocket, address[0], int(decodedmsg[1])))
                    self.threads[thread.name] = thread
                    thread.start()
                else:
                    print("invalid response received after sending audio parameters. closing connection")
                    clientsocket.close()
            else:
                print("invalid identity {}. terminating connection".format(decodedmsg))
                clientsocket.send(bytes("i have nothing for you", "utf-8"))
                clientsocket.close()
        except ConnectionError as e:
            print("ConnectionError:", e.errno, e.strerror)
            clientsocket.close()

    def begin_rolling_buffer(self):
        thread = Thread(target=self.rolling_buffer, name="rolling buffer", daemon=True)
        self.threads["rolling_buffer"] = thread
        thread.start()
        while len(self.audio_buffer) < self.buffer_size:
            pass

    def rolling_buffer(self):
        print("pre-filling audio buffer")
        while len(self.audio_buffer) < self.buffer_size:
            next_chunk = self.get_next_chunk()
            next_chunk = self.compress_data(next_chunk) if self.use_compression > 0 else next_chunk
            self.audio_buffer.append(next_chunk)
            self.buffer_id += 1
        print("buffer pre-fill complete - ready for connections")
        last_buffer_optimize = time.time()
        while True:
            next_chunk = self.get_next_chunk()
            next_chunk = self.compress_data(next_chunk) if self.use_compression > 0 else next_chunk
            self.audio_buffer.append(next_chunk)
            if len(self.audio_buffer) > self.buffer_size:
                self.audio_buffer = self.audio_buffer[-self.buffer_size:]
            self.buffer_id += 1
            if time.time() - last_buffer_optimize > self.buffer_optimize_time:
                if self.buffer_size > self.buffer_min_size \
                        and self.highest_buffer_pos < len(self.audio_buffer) - self.buffer_size_increment:
                    self.buffer_size -= self.buffer_size_increment
                    print("max load {} / {}. dropping size to {}".format(self.highest_buffer_pos,
                                                                         len(self.audio_buffer), self.buffer_size))
                else:
                    print("max load {} / {}".format(self.highest_buffer_pos, len(self.audio_buffer)))
                last_buffer_optimize = time.time()
                self.highest_buffer_pos = 1

    @staticmethod
    def add_bytes_to_data(data, *args):
        for arg in args:
            data += arg
        return data

    def compress_data(self, data):
        if self.use_compression == 1:
            return self.compress_interpolate(data)
        elif self.use_compression == 2:
            return self.compress_data_fill(data)

    @staticmethod
    def compress_interpolate(data):
        if data is None:
            return data
        data_cursor = 0
        new_data = bytes()
        while data_cursor < len(data):
            new_data += data[data_cursor:data_cursor+2]
            data_cursor += 4
        return new_data

    @staticmethod
    def compress_data_fill(data):
        if data is None:
            return data
        data_as_ints = []
        cursor = [c for c in range(0, len(data), 2)]
        for c in cursor:
            data_as_ints.append(int.from_bytes(data[c:c + 1], "little", signed=True))
        data = data_as_ints
        if sum(data) < 5:
            return bytes(2)
        new_data = bytes()
        new_data += data[0].to_bytes(2, "little", signed=True)
        direction = 1 if data[1] >= data[0] else -1
        cursor = abs(direction)
        zero_string = False
        while cursor < len(data) - 1:
            if data[cursor+1] == 0 and zero_string is False:
                new_data += direction.to_bytes(1, "little", signed=True)
                new_data += data[cursor].to_bytes(2, "little", signed=True)
                direction = 1
                zero_string = True
            elif data[cursor+1] == 0 and zero_string is True:
                direction += 1
            elif data[cursor+1] != 0 and zero_string is True:
                new_data += bytes([0])
                new_data += direction.to_bytes(2, "little", signed=True)
                direction = 1 if data[cursor] > 0 else -1
                zero_string = False
            elif data[cursor + 1] >= data[cursor] and direction > 0 and zero_string is False:
                direction += 1
            elif data[cursor + 1] < data[cursor] and direction > 0 and zero_string is False:
                new_data += direction.to_bytes(1, "little", signed=True)
                new_data += data[cursor].to_bytes(2, "little", signed=True)
                direction = -1
            elif data[cursor + 1] > data[cursor] and direction < 0 and zero_string is False:
                new_data += direction.to_bytes(1, "little", signed=True)
                new_data += data[cursor].to_bytes(2, "little", signed=True)
                direction = 1
            elif data[cursor + 1] <= data[cursor] and direction < 0 and zero_string is False:
                direction -= 1
            if abs(direction) == 127:
                new_data += direction.to_bytes(1, "little", signed=True)
                new_data += data[cursor].to_bytes(2, "little", signed=True)
                direction = 1 if direction > 0 else -1
            cursor += 1
        if data[cursor] == 0:
            new_data += bytes([0])
            new_data += direction.to_bytes(2, "little", signed=True)
        else:
            new_data += direction.to_bytes(1, "little", signed=True)
            new_data += data[cursor].to_bytes(2, "little", signed=True)
        return new_data

    def send_audio_loop(self, clientsocket, address, client_buffer_size):
        done = False
        current_buffer_id = self.buffer_id - client_buffer_size
        cur_buf_pos = client_buffer_size
        while not done:
            try:
                if cur_buf_pos < 1:
                    cur_buf_pos = 1
                    current_buffer_id = self.buffer_id
                    print("server buffer is lagging")
                elif cur_buf_pos > len(self.audio_buffer):
                    cur_buf_pos = len(self.audio_buffer)
                    current_buffer_id = self.buffer_id - len(self.audio_buffer)
                    if self.buffer_size + self.buffer_size_increment <= self.buffer_max_size:
                        self.buffer_size += self.buffer_size_increment
                        print("{} is lagging. increasing server buffer to {}".format(address, self.buffer_size))
                    else:
                        print("{} is lagging but server buffer is at max ({})".format(address, self.buffer_size))

                next_chunk = self.audio_buffer[-cur_buf_pos]

                # funky buffer magic to help clients stay away from end of buffer
                have_next_chunk = False
                moved_positions = 0
                while have_next_chunk is False:
                    if ((self.use_compression == 0 and sum(next_chunk) < 5)
                            or self.use_compression > 0 and len(next_chunk) == 2 and next_chunk == bytes(2))\
                            and cur_buf_pos > 2:
                        cur_buf_pos -= 1
                        current_buffer_id += 1
                        moved_positions += 1
                        next_chunk = self.audio_buffer[-cur_buf_pos]
                    else:
                        have_next_chunk = True
                        if ((self.use_compression == 0 and sum(next_chunk) < 5)
                                or self.use_compression > 0 and len(next_chunk) == 2 and next_chunk == bytes(2)):
                            next_chunk = bytes(2)
                if moved_positions > 1:
                    print("{} buffer move {} -> {} ({})".format(address, cur_buf_pos + moved_positions, cur_buf_pos,
                                                                moved_positions))
                # end buffer magic

                if self.use_compression > 0:
                    clientsocket.send(len(next_chunk).to_bytes(2, "little", signed=True))
                    msg = clientsocket.recv(2)
                    if msg != len(next_chunk).to_bytes(2, "little", signed=True):
                        print("client did not respond properly to data size sent")
                        raise ConnectionError
                clientsocket.send(next_chunk)
                msg = clientsocket.recv(self.CHUNK)
                if current_buffer_id + 1 <= self.buffer_id:
                    current_buffer_id += 1
                cur_buf_pos = (self.buffer_id - current_buffer_id) + 1
                if cur_buf_pos > self.highest_buffer_pos:
                    self.highest_buffer_pos = cur_buf_pos if cur_buf_pos <= self.buffer_size else self.buffer_size
            except (ConnectionError, socket.timeout) as e:
                done = True
                if type(e) == ConnectionError:
                    print(address, e.errno, e.strerror)
                else:
                    print("{} socket timeout".format(address))
                self.close_connection(clientsocket, address)
            else:
                decodedmsg = msg.decode("utf-8")
                if decodedmsg != "ok":
                    print("client said '{}' so ending audio loop".format(decodedmsg))
                    self.close_connection(clientsocket, address)
                    done = True

    def close_connection(self, clientsocket, address):
        try:
            clientsocket.close()
            del self.clients[address]
            print("{} clients remaining".format(len(self.clients)))
        except KeyError:
            print("client {} not found in clients".format(address))
        try:
            del self.threads[address]
            print("{} threads running".format(len(self.threads)))
        except KeyError:
            print("client {} not found in threads".format(address))

    def file_data_reader(self):
        for i in self.file_stream:
            yield i
        return None

    def get_next_chunk(self):
        if self.filename is None:
            while self.live_stream.get_read_available() < self.CHUNK:
                pass
            data = self.live_stream.read(self.CHUNK)
#             print("{} frames left to read".format(self.live_stream.get_read_available()))
        else:
            data = bytes()
            while not self.file_finished and len(data) < self.CHUNK * 2:
                try:
                    data += next(self.file_data)
                except StopIteration:
                    self.file_finished = True
                    print("reached end of file")
        return data


if __name__ == "__main__":
    audio = AudioServer(audio_buffer_size=102,  use_compression=0)
    # audio = AudioServer(filename="freq_test.opus")
    while True:
        audio.wait_for_connection()
