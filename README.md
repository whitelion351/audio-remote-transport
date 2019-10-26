# audio-remote-transport
Transport audio to a remote system

An audio server/client system. Server grabs audio from default input device. Clients can connect to the server and be served the audio data, which they play over the systems default output sound device. Server can also take a file as input

Currently no data compression across the link is implemented, however on a LAN it works pretty well. Even across a wireless link. Audio quality defaults to a sample rate of 44100Khz with 16 bit samples, chunk size of 2048 and buffer size of 6 chunks on server side and 12 on client side. This has a latency of ~1 sec. 

## requirements
Python 3.5 or above (only tested on Linux x64)

pip install the following modules:

pyaudio

audioread

As stated in one of my other repos, Linux users need to apt-get install portaudiov19-dev. Windows users need pip install pywin though that is untested. I only use windows to play League of Legends.

## options
pass --configure_devices=True on the command line or when instancing the class to choose devices to use for input/output. 
This is only available for the server for now.

...To be continued
## todo
add options to choose different devices by index - DONE

audio data compression across the server/client connection - Being worked on as we speak

Documentation for all the extra options I have added to the class. Most are buffer performance options

Add device config code to the client
