from fastapi import FastAPI

app=FastAPI()


@app.get( "/")
def home ():
    return{"name: Cerberus  version: 0.0.1"}
