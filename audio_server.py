import pyaudio
import audioread
import socket
from threading import Thread


class AudioServer:
    # noinspection SpellCheckingInspection
    def __init__(self, filename=None, chunk=2048, audio_format=pyaudio.paInt16, channels=1, rate=44100,
                 bind_address="0.0.0.0", bind_port=1060, audio_buffer_size=12):
        # constants
        self.CHUNK = chunk             # samples per frame
        self.FORMAT = audio_format     # audio format (bytes per sample?)
        self.CHANNELS = channels       # single channel for microphone
        self.RATE = rate               # samples per second
        self.wave_data = None
        self.filename = filename
        self.file_finished = False
        self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connection.bind((bind_address, bind_port))
        self.connection.listen(5)
        self.clients = {}
        self.threads = {}
        self.buffer_size = audio_buffer_size
        self.audio_buffer = []
        self.buffer_id = -1
        print("audio server running on {}:{}".format(bind_address, bind_port))

        if self.filename is None:
            # pyaudio class instance
            live_audio = pyaudio.PyAudio()

            # stream object to get data from microphone
            self.live_stream = live_audio.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                output=False,
                frames_per_buffer=self.CHUNK
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

    def wait_for_connection(self):
        clientsocket, address = self.connection.accept()
        clientsocket.settimeout(5)
        msg = clientsocket.recv(self.CHUNK)
        decodedmsg = msg.decode("utf-8")
        print("connection received from {}".format(address))
        if decodedmsg == "AudioClient":
            print("type is {}. sending audio parameters".format(decodedmsg))
            params = "{},{}".format(self.RATE, self.CHUNK)
            clientsocket.send(bytes(params, "utf-8"))
            msg = clientsocket.recv(self.CHUNK)
            if msg.decode("utf-8") == "ok":
                print("client thinks it is ready")
                if "rolling_buffer" not in self.threads.keys():
                    print("starting server buffer thread")
                    self.begin_rolling_buffer()
                    while len(self.audio_buffer) < self.buffer_size:
                        pass
                self.clients[address[0]] = clientsocket
                thread = Thread(target=self.send_audio_loop, name=address[0],
                                daemon=True, args=(clientsocket, address[0]))
                print("creating client thread {}".format(thread.name))
                self.threads[thread.name] = thread
                thread.start()
            else:
                print("invalid response received after sending audio parameters. closing connection")
                clientsocket.close()
        else:
            print("type is {}. terminating connection".format(decodedmsg))
            clientsocket.send(bytes("i have nothing for you", "utf-8"))
            clientsocket.close()

    def begin_rolling_buffer(self):
        thread = Thread(target=self.rolling_buffer, daemon=True)
        self.threads["rolling_buffer"] = thread
        thread.start()

    def rolling_buffer(self):
        print("pre-filling audio buffer")
        while len(self.audio_buffer) < self.buffer_size:
            self.audio_buffer.append(self.get_next_chunk())
            self.buffer_id += 1
        print("buffer pre-fill complete")
        while True:
            if self.live_stream.get_read_available() >= self.CHUNK:
                self.audio_buffer.append(self.get_next_chunk())
                self.audio_buffer.pop(0)
                self.buffer_id += 1

    def send_audio_loop(self, clientsocket, address):
        done = False
        current_buffer_id = self.buffer_id - self.buffer_size
        current_buffer_position = self.buffer_size
        while not done:
            try:
                # print("client {} id {} max {} position {}".format(address, current_buffer_id,
                #                                                   self.buffer_id, current_buffer_position))
                next_chunk = self.audio_buffer[-current_buffer_position]
                clientsocket.send(next_chunk)
                msg = clientsocket.recv(self.CHUNK)
                if current_buffer_id + 1 <= self.buffer_id:
                    current_buffer_id += 1
                current_buffer_position = (self.buffer_id - current_buffer_id) + 1
                if current_buffer_position < 1:
                    current_buffer_position = 2
                    current_buffer_id = self.buffer_id - 1
                elif current_buffer_position > self.buffer_size:
                    current_buffer_position = self.buffer_size
                    current_buffer_id = self.buffer_id - self.buffer_size
                    print("{} is falling behind".format(address))
            except Exception as e:
                done = True
                print("sending audio to {} failed".format(address), e)
                self.close_connection(clientsocket, address)
            else:
                decodedmsg = msg.decode("utf-8")
                if decodedmsg != "ok":
                    print("client said {} so ending audio loop".format(decodedmsg))
                    self.close_connection(clientsocket, address)
                    done = True

    def close_connection(self, clientsocket, address):
        try:
            clientsocket.close()
            del self.clients[address]
            print ("{} clients remaining".format(len(self.clients)))
        except KeyError:
            print("client {} not found in clients".format(address))
        try:
            del self.threads[address]
            print ("{} threads running".format(len(self.threads)))
        except KeyError:
            print("client {} not found in threads".format(address))

    def file_data_reader(self):
        for i in self.file_stream:
            yield i
        return None

    def get_next_chunk(self):
        if self.filename is None:
            data = self.live_stream.read(self.CHUNK)
#            print("{} frames left to read".format(self.live_stream.get_read_available()))
        else:
            data = bytes()
            while not self.file_finished and len(data) < self.CHUNK * 2:
                try:
                    data += next(self.file_data)
                except StopIteration:
                    self.file_finished = True
                    print("reached end of file")
        return data

    def compress_data(self, data=None):
        """Compresses audio for sending to remote clients
        Not currently implemented"""
        if data is not None:
            return data
        print("No data to compress")
        return None


if __name__ == "__main__":
    audio = AudioServer()
    # audio = AudioServer(filename="freq_test.opus")
    print("waiting for connections")
    while True:
        audio.wait_for_connection()
