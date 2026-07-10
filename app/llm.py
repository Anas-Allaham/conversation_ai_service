# app/llm.py

import os

import google.generativeai as genai

from dotenv import load_dotenv


# ======================
# LOAD ENV
# ======================

load_dotenv()


API_KEY = os.getenv(

    "GEMINI_API_KEY"

)


genai.configure(

    api_key=API_KEY

)


# ======================
# LOAD MODEL
# ======================

model = genai.GenerativeModel(

    "gemini-2.5-flash"

)


# ======================
# GENERATE RESPONSE
# ======================

def generate_response(

        user_text,

        conversation_history

):


    system_prompt = """

You are an English learning tutor in a real-time voice conversation.

Rules:

1. Detect user intent automatically.

2. Adapt response style:

- Greetings → short and natural

- Casual conversation → conversational

- Grammar explanations → explain gradually

- Vocabulary → focused

- Pronunciation → focused

3. Avoid huge spoken paragraphs.

4. Give information in conversational chunks.

5. Ask:

"Would you like an example?"

when useful.

6. Sound natural.

7. Prefer 2–4 sentences unless user asks for details.

8. Keep conversation flowing naturally.

"""


    prompt = (

        system_prompt

        +

        "\n\nConversation:\n"

    )


    for msg in conversation_history:

        role = msg["role"]

        content = msg["content"]


        prompt += (

            f"{role}: "

            f"{content}\n"

        )


    prompt += (

        f"user: {user_text}\n"

        f"assistant:"

    )


    try:


        response = (

            model.generate_content(

                prompt

            )

        )


        answer = (

            response.text

            .strip()

        )


        return answer


    except Exception as e:


        print(

            "\nGEMINI ERROR:",

            e

        )


        return (

            "Sorry, I lost connection."

        )