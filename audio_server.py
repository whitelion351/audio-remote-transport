import socket
from threading import Thread
import argparse
import time
import numpy as np
import pyaudio
import audioread


class AudioServer:
    # noinspection SpellCheckingInspection
    def __init__(self, filename=None, chunk=2048, audio_format=pyaudio.paInt16, channels=1, rate=44100,
                 bind_address="0.0.0.0", bind_port=1060, audio_buffer_size=102, buffer_size_increment=6,
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
        self.config_filename = config_filename
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.bind_address = bind_address
        self.bind_port = bind_port
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
                    with open(self.config_filename, "r") as file:
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
                output=True,
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
            live_audio = pyaudio.PyAudio()
            self.live_stream = live_audio.open(

                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                output=True,
                frames_per_buffer=self.CHUNK,
                input_device_index=self.input_device_index,
                output_device_index=self.input_device_index
             )

        print('stream started')

    def configure_this_instance(self, instance):
        print("Listing available APIs")
        host_api_count = instance.get_host_api_count()
        info_list = []
        for i in range(host_api_count):
            info = instance.get_host_api_info_by_index(i)
            print(i+1, ") ", info, sep="")
            info_list.append(info)
        if len(info_list) < 1:
            print("No APIs available. Configure can not continue. Hopefully the defaults work for you")
            return
        user_choice = input("Choose api: ")
        user_choice = int(user_choice) - 1
        host_api_info = info_list[user_choice]
        host_api_index = host_api_info["index"]
        print("using host api:", host_api_info["name"])

        print("Listing devices available to the API")
        info_list = []
        for i in range(instance.get_device_count()):
            info = instance.get_device_info_by_index(i)
            if info["hostApi"] == host_api_index:
                print("{}) name: {}, inputs: {}, outputs: {}, defaultRate: {}, deviceIndex: {}".format(
                    i+1, info["name"], info["maxInputChannels"], info["maxOutputChannels"],
                    info["defaultSampleRate"], info["index"]
                ))
                info_list.append(info)
        if len(info_list) < 1:
            print("No devices available for this API. Configure can not continue. Hopefully the defaults work for you")
            return
        user_choice = input("Choose input device: ")
        user_choice = int(user_choice) - 1
        input_device_info = info_list[user_choice]
        input_device_index = input_device_info["index"]
        print("using {} for input".format(input_device_info["name"]))
        user_choice = input("Choose output device: ")
        user_choice = int(user_choice) - 1
        output_device_info = info_list[user_choice]
        output_device_index = output_device_info["index"]
        print("using {} for output".format(input_device_info["name"]))
        self.input_device_index = input_device_index
        self.output_device_index = output_device_index
        with open(self.config_filename, "w") as file:
            file.write("input_device_index:" + str(self.input_device_index) + "\n")
            file.write("output_device_index:" + str(self.output_device_index) + "\n")
        return

    def wait_for_connection(self):
        if "rolling_buffer" not in self.threads.keys():
            print("starting server buffer thread")
            self.begin_rolling_buffer()
        print("audio server running on {}:{}".format(self.bind_address, self.bind_port))
        while True:
            client_socket, address = self.connection.accept()
            client_socket.settimeout(5)
            try:
                msg = client_socket.recv(self.CHUNK)
                decoded_msg = msg.decode("utf-8").split(sep=",")
                print("connection received from {}".format(address))
                if decoded_msg[0] == "AudioClient" and len(decoded_msg) > 1:
                    print("type is {} with buffer size {}. sending audio parameters".format(decoded_msg[0], decoded_msg[1]))
                    params = "{},{},{}, {}".format(self.RATE, self.CHUNK, self.CHANNELS, self.use_compression)
                    client_socket.send(bytes(params, "utf-8"))
                    msg = client_socket.recv(self.CHUNK)
                    d_msg = ""
                    try:
                        d_msg = msg.decode("utf-8")
                    except UnicodeDecodeError as e:
                        print(e)
                    if d_msg == "ok":
                        print("creating client thread {}".format(address[0]))
                        self.clients[address[0]] = client_socket
                        thread = Thread(target=self.send_audio_loop, name=address[0], daemon=True,
                                        args=(client_socket, address[0], int(decoded_msg[1]), decoded_msg[-1]))
                        self.threads[thread.name] = thread
                        thread.start()
                    else:
                        d_msg = "'" + d_msg + "'"
                        print("received {} {} after sending parameters. closing connection".format(msg, d_msg))
                        client_socket.close()
                else:
                    print("invalid identity {}. terminating connection".format(decoded_msg))
                    client_socket.send(bytes("i have nothing for you", "utf-8"))
                    client_socket.close()
            except ConnectionError as e:
                print("ConnectionError:", e.errno, e.strerror)
                client_socket.close()

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
                elif len(self.clients) > 0:
                    print("max load {} / {}".format(self.highest_buffer_pos, len(self.audio_buffer)))
                last_buffer_optimize = time.time()
                self.highest_buffer_pos = 1

    def compress_data(self, data):
        if self.use_compression == 1:
            return self.compress_interpolate(data)
        elif self.use_compression == 2:
            return self.compress_data_fill(data)

    @staticmethod
    def compress_interpolate(data):
        if data is None:
            return data
        data = np.frombuffer(data, dtype=np.int16)
        data_value = np.sum(data)
        if 5 > data_value > -5:
            return bytes(2)
        condition = []
        for _ in range(len(data) // 2):
            condition += [True, False]
        new_data = data[condition].tobytes()
        return new_data

    @staticmethod
    def compress_data_fill(data):
        if data is None:
            return data
        data = np.frombuffer(data, dtype=np.int16)
        data_value = np.sum(data)
        if 5 > data_value > -5:
            return bytes(2)
        total_data_cords = 0
        data_cords = []
        new_data = []
        direction = 1 if data[1] >= data[0] else -1
        matching_values = False
        last_value = None
        for cursor, value in enumerate(data):
            if cursor == 0:
                new_data.append(value)
                data_cords.append(cursor)
                total_data_cords += 1
            elif cursor == len(data) - 1:
                new_data.append(value)
                data_cords.append(cursor)
                total_data_cords += 1
            elif value < last_value and direction == 1:
                new_data.append(data[cursor-1])
                data_cords.append(cursor-1)
                total_data_cords += 1
                direction = -1
            elif value > last_value and direction == -1:
                new_data.append(data[cursor-1])
                data_cords.append(cursor-1)
                total_data_cords += 1
                direction = 1
            elif value == last_value:
                if not matching_values:
                    matching_values = True
                    new_data.append(value)
                    data_cords.append(cursor - 1)
                    total_data_cords += 1
                elif data[cursor + 1] != value:
                    matching_values = False
                    new_data.append(value)
                    data_cords.append(cursor)
                    total_data_cords += 1
                    direction = 1 if data[cursor + 1] >= value else -1
            last_value = value
        if len(data_cords) != len(new_data):
            print("compress error. tot cords {} len cords {} len data {}".format(total_data_cords, len(data_cords),
                                                                                 len(new_data)))
        new_data = [total_data_cords] + data_cords + new_data
        byte_data = np.array(new_data, dtype=np.int16).tobytes()
        return byte_data

    def send_audio_loop(self, client_socket, address, client_buffer_size, use_magic):
        magic_enabled = True if use_magic == "true" else False
        done = False
        current_buffer_id = self.buffer_id - client_buffer_size
        cur_buf_pos = client_buffer_size if client_buffer_size < len(self.audio_buffer) - self.buffer_size_increment \
            else len(self.audio_buffer) - self.buffer_size_increment
        print("client starting at buffer position", cur_buf_pos)
        while not done:
            try:
                if cur_buf_pos < 1:
                    cur_buf_pos = 1
                    current_buffer_id = self.buffer_id
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
                            or self.use_compression > 0 and next_chunk == bytes(2))\
                            and cur_buf_pos > 2 and magic_enabled is True:
                        cur_buf_pos -= 1
                        current_buffer_id += 1
                        moved_positions += 1
                        next_chunk = self.audio_buffer[-cur_buf_pos]
                    else:
                        have_next_chunk = True
                        if ((self.use_compression == 0 and sum(next_chunk) < 5)
                                or self.use_compression > 0 and next_chunk == bytes(2)) and magic_enabled is True:
                            next_chunk = bytes(2)
                if moved_positions > 1:
                    print("{} buffer move {} -> {} ({})".format(address, cur_buf_pos + moved_positions, cur_buf_pos,
                                                                moved_positions))
                # end buffer magic

                header = None
                if self.use_compression > 0:
                    header = len(next_chunk).to_bytes(2, "little", signed=True)
                    client_socket.send(header)
                    msg = client_socket.recv(2)
                    if msg != header:
                        raise ConnectionError("client responded to data size {} with {}".format(header, msg))
                client_socket.send(next_chunk)
                msg = client_socket.recv(self.CHUNK)
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
                self.close_connection(client_socket, address)
            else:
                try:
                    decoded_msg = msg.decode("utf-8")
                except UnicodeDecodeError:
                    print("error decoding client msg after sent data. client sent {} instead of ok".format(msg))
                    if self.use_compression > 0 and msg == header:
                        print("that response matches the sent header")
                else:
                    if decoded_msg != "ok":
                        print("client said '{}' so ending audio loop".format(decoded_msg))
                        self.close_connection(client_socket, address)
                        done = True

    def close_connection(self, client_socket, address):
        try:
            client_socket.close()
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
            while self.live_stream.get_read_available() < self.CHUNK * self.CHANNELS:
                time.sleep(0.1)
            data = self.live_stream.read(self.CHUNK * self.CHANNELS)
#             print("{} frames left to read".format(self.live_stream.get_read_available()))
        else:
            self.live_stream.read(self.CHUNK)
            data = bytes()
            while not self.file_finished and len(data) < self.CHUNK * 2 * self.CHANNELS:
                try:
                    data += next(self.file_data)
                except StopIteration:
                    self.file_finished = True
                    print("reached end of file")
        return data


if __name__ == "__main__":
    audio = AudioServer(rate=44100, audio_buffer_size=108,  configure_devices=False, use_compression=0)
    # audio = AudioServer(filename="../music/freqtest.mp3")
    audio.wait_for_connection()
