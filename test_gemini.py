from app.llm import generate_response


history = []


response = generate_response(

    "Hello",

    history

)


print(

    response

)