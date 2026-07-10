# This orchestrates EVERYTHING.
# flow
# record audio
# → transcribe
# → generate AI response
# → synthesize speech
# → play speech

from app.interruption import capture_interruption, detect_interruption
from app.vad_recorder import record_until_silence
from app.transcriber import transcribe_audio
from app.llm import generate_response
from app.tts import text_to_speech
from app.player import is_playing, play_audio, stop_audio


def main():

    print("\n=== Real-Time English Tutor ===\n")

    conversation_history = []

    while True:

        # Listen
        audio_path = record_until_silence()

        # Transcribe
        user_text = transcribe_audio(audio_path)

        if len(user_text) < 2:
            print("Ignoring empty transcription")
            continue

        if user_text.lower() in [
            "thank you for some very helpful presentation"
        ]:
            continue

        if not user_text.strip():
            continue

        print(f"\nYou: {user_text}")

        # Exit command
        if user_text.lower() in [
            "bye",
            "goodbye",
            "exit",
            "stop conversation"
        ]:

            farewell = "Goodbye! Talk to you later."

            audio = text_to_speech(farewell)

            play_audio(audio)

            break

        # Generate response
        ai_response = generate_response(
            user_text,
            conversation_history
        )

        print(f"\nAI: {ai_response}")

        # Save conversation memory
        conversation_history.append({
            "role":"user",
            "content":user_text
        })

        conversation_history.append({
            "role":"assistant",
            "content":ai_response
        })

        # Speak response
        audio = text_to_speech(
            ai_response
        )

        play_audio(
            audio
        )

        interrupted = (

    detect_interruption()

)


        if interrupted:

            stop_audio()


            interruption_audio = (

                capture_interruption()

            )


            if interruption_audio is None:

                continue


            user_text = (

                transcribe_audio(

                    interruption_audio

                )

            )


            if not user_text.strip():

                continue


            print(

                f"\nInterrupted:\n"

                f"{user_text}"

            )


            conversation_history.append({

                "role":"user",

                "content":user_text

            })


            ai_response = (

                generate_response(

                    user_text,

                    conversation_history

                )

            )


            conversation_history.append({

                "role":"assistant",

                "content":ai_response

            })


            audio = (

                text_to_speech(

                    ai_response

                )

            )


            play_audio(

                audio

            )
        
        

if __name__=="__main__":
    main()