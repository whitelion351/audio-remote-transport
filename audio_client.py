from time import sleep
from threading import Thread
import socket
import pyaudio
import numpy as np


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
        self.use_compression = 0
        self.last_sample = 0
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

        print('audio stream running')

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
                self.connection.settimeout(3)
                info = "AudioClient,"+str(self.buffer_size)
                self.connection.send(bytes(info, "utf-8"))
                data = self.connection.recv(self.CHUNK)
                data = data.decode("utf-8").split(sep=",")
                data = [int(d) for d in data if d != ","]
                self.RATE = data[0]
                self.CHUNK = data[1]
                self.use_compression = data[2]
                print("using samplerate: {}, chunksize: {}, compression: {}".format(self.RATE, self.CHUNK,
                                                                                    self.use_compression))
                self.connection.send(bytes("ok", "utf-8"))
            except Exception as e:
                print(e)
                retries -= 1
                print("connection failed. retries remaining:", retries)
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
                self.connect_to_server()
                self.fill_buffer()
                thread.start()
            while self.live_stream.get_write_available() > self.CHUNK and self.is_connected:
                if len(self.audio_buffer) == 0:
                    print("buffer empty")
                    sleep(1)
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
        while len(self.audio_buffer) < self.buffer_size and self.is_connected:
            data = self.get_next_chunk()
            data = self.decompress_data(data) if self.use_compression > 0else data
            if data is None:
                print("a chunk was None")
                break
            else:
                self.audio_buffer.append(data)

    def get_next_chunk(self):
        data_size = self.CHUNK if self.use_compression > 0 else self.CHUNK * 2
        data = bytes()
        while len(data) < data_size:
            try:
                chunk_data = self.connection.recv(data_size)
                if len(chunk_data) == 0:
                    raise ConnectionError
                elif len(chunk_data) == 2:
                    if chunk_data == bytes(2):
                        data = bytes(data_size)
                    else:
                        data_size = int.from_bytes(chunk_data, "little", signed=True)
                        self.connection.send(chunk_data)
                else:
                    data += chunk_data
            except (ConnectionError, socket.timeout) as e:
                print("failed getting chunk:", e)
                self.connection.close()
                self.is_connected = False
                return None
        self.connection.send(bytes("ok", "utf-8"))
        return data

    def decompress_data(self, data):
        if self.use_compression == 1:
            return self.decompress_interpolate(data)
        elif self.use_compression == 2:
            return self.decompress_data_fill(data)

    def decompress_interpolate(self, data):
        if data is None:
            return data
        if sum(data) < 5:
            return bytes(self.CHUNK * 2)
        last_sample = self.last_sample
        new_data = bytes()
        d_curse_s = list(range(0, len(data), 2))
        d_curse_f = list(range(2, len(data)+1, 2))
        for d_curse in range(len(d_curse_s)):
            current_sample = int.from_bytes(data[d_curse_s[d_curse]:d_curse_f[d_curse]],
                                            byteorder="little", signed=True)
            new_sample = last_sample + (current_sample - last_sample) // 2 if current_sample > last_sample \
                else last_sample - (last_sample - current_sample) // 2
            new_sample = new_sample.to_bytes(length=2, byteorder="little", signed=True)
            new_data += new_sample + data[d_curse_s[d_curse]:d_curse_f[d_curse]]
            last_sample = current_sample
            d_curse += 1
        self.last_sample = last_sample
        return new_data

    def decompress_data_fill(self, data):
        if data is None:
            return data
        if len(data) == 2:
            return bytes(self.CHUNK * 2)
        data_as_ints = []
        cursor = [i for i in range(2, len(data), 3)]
        data_as_ints.append(int.from_bytes(data[:2], "little", signed=True))
        for c in cursor:
            byte = data[c]
            byte = (256-byte) * (-1) if byte > 127 else byte
            data_as_ints.append(byte)
            data_as_ints.append(int.from_bytes(data[c+1:c+3], "little", signed=True))
        data = data_as_ints
        new_data = bytes()
        new_data += data[0].to_bytes(2, "little", signed=True)
        cursor = 1
        while cursor < len(data):
            if data[cursor] == 0:
                new_data += bytes(data[cursor+1] * 2)
            else:
                values = np.linspace(data[cursor - 1], data[cursor + 1], abs(data[cursor]) + 1).astype(np.int16)[1:]
                for v in values:
                    new_data += int(v).to_bytes(2, "little", signed=True)
            cursor += 2
        return new_data

    def write_audio_to_stream(self, data):
        if data is None:
            return
        self.live_stream.write(data)
        return


if __name__ == "__main__":
    audio = AudioClient()
    audio.set_server("192.168.5.121", 1060)
    audio.play_audio_stream()
