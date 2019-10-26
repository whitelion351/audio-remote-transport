from time import sleep
from threading import Thread
import socket
import pyaudio


class AudioClient:
    # noinspection SpellCheckingInspection
    def __init__(self, chunk=2048, audio_format=pyaudio.paInt16, channels=1, rate=44100, audio_buffer_size=96):
        # constants
        self.CHUNK = chunk             # samples per frame
        self.FORMAT = audio_format     # audio format (bytes per sample?)
        self.CHANNELS = channels       # single channel for microphone
        self.RATE = rate               # samples per second
        self.live_stream = None
        self.connection = None
        self.server_address = None
        self.server_port = None
        self.is_connected = False
        self.buffer_size = audio_buffer_size
        self.audio_buffer = []
        self.threads = {}

    def create_audio_stream(self):
        stream = pyaudio.PyAudio()
        self.live_stream = stream.open(
            format=self.FORMAT,
            channels=self.CHANNELS,
            rate=self.RATE,
            input=False,
            output=True,
            frames_per_buffer=self.CHUNK
        )

        print('audio stream ready')

    def set_server(self, address=None, port=None):
        if address is None or port is None:
            print("you need to specify an address and port, ya big ninnie")
        else:
            self.server_address = address
            self.server_port = port

    def connect_to_server(self):
        retries = 3
        print("connecting to audio server at {}:{}".format(self.server_address, self.server_port))
        while retries > 0 and not self.is_connected:
            try:
                self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.connection.connect((self.server_address, self.server_port))
                self.connection.settimeout(2)
                info = "AudioClient,"+str(self.buffer_size)
                self.connection.send(bytes(info, "utf-8"))
                data = self.connection.recv(self.CHUNK)
                data = data.decode("utf-8").split(sep=",")
                data = [int(d) for d in data if d != ","]
                self.RATE = data[0]
                self.CHUNK = data[1]
                print("using samplerate: {}, chunksize: {}".format(self.RATE, self.CHUNK))
                self.connection.send(bytes("ok", "utf-8"))
            except Exception as e:
                print(e)
                retries -= 1
                print("connection failed. retries remaining: {}".format(retries))
                sleep(2)
            else:
                self.is_connected = True
                print("connection established")
                self.create_audio_stream()

    def play_audio_stream(self):
        done = False
        while done is False:
            if "buffer_control" not in self.threads.keys():
                print("starting buffer thread")
                thread = Thread(target=self.buffer_control, name="buffer_control", daemon=True)
                self.threads[thread.name] = thread
                thread.start()
            while len(self.audio_buffer) < self.buffer_size:
                pass
            while self.live_stream.get_write_available() > self.CHUNK:
                if len(self.audio_buffer) == 0:
                    print("buffer empty")
                    break
                data = self.audio_buffer.pop(0) if len(self.audio_buffer) > 0 else None
                self.write_audio_to_stream(data)

    def buffer_control(self):
        while True:
            if not self.is_connected:
                self.connect_to_server()
            if len(self.audio_buffer) < self.buffer_size:
                self.fill_buffer()

    def fill_buffer(self):
        while len(self.audio_buffer) < self.buffer_size:
            data = self.get_next_chunk()
            if data is None or len(data) < self.CHUNK * 2:
                print("not enough or no audio data when filling buffer")
                break
            else:
                self.audio_buffer.append(data)

    def get_next_chunk(self):
        data = bytes()
        while len(data) < self.CHUNK * 2:
            try:
                chunk_data = self.connection.recv(self.CHUNK * 2)
                if len(chunk_data) == 0:
                    raise ConnectionError
                elif len(chunk_data) == 3 and list(chunk_data) == [0, 0, 0]:
                    data = bytes(self.CHUNK * 2)
                else:
                    data += chunk_data
            except (ConnectionError, socket.timeout) as e:
                print("failed getting chunk:", e)
                self.connection.close()
                self.is_connected = False
                return None
        self.connection.send(bytes("ok", "utf-8"))
        return data

    def write_audio_to_stream(self, data):
        if data is None:
            # print("not enough or no data to write to audio stream")
            return self.live_stream.get_write_available()
        self.live_stream.write(data)
        return self.live_stream.get_write_available()


if __name__ == "__main__":
    audio = AudioClient()
    audio.set_server("192.168.5.121", 1060)
    audio.play_audio_stream()
