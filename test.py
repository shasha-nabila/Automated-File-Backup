import requests

url = "https://filearch-funcapp.azurewebsites.net/api/upload?"  # function URL
files = {"file": open("C:\\Users\\DELL\\Downloads\\test.jpg", "rb")}  # path to the file

response = requests.post(url, files=files)

print(response.text)
