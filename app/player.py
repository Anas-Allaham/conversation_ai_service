# This:
# plays generated mp3

import pygame

pygame.mixer.init()


def play_audio(audio_file):

    pygame.mixer.music.stop()

    try:
        pygame.mixer.music.unload()

    except:
        pass


    pygame.mixer.music.load(
        audio_file
    )

    pygame.mixer.music.play()

    print(
        "Playback started"
    )


def stop_audio():

    pygame.mixer.music.stop()

    print(
        "Playback stopped"
    )


def is_playing():

    return pygame.mixer.music.get_busy()