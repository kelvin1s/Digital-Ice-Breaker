from flask import Flask, render_template, request, session, redirect, url_for, flash, send_file
from flask_socketio import join_room, leave_room, send, emit, SocketIO
import random
from string import ascii_uppercase
from pyngrok import ngrok
import qrcode
from datetime import datetime, timedelta
import time
import math
import io
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
socketio = SocketIO(app)

rooms = {}  #nested dictionary which stores active events, where every event has a dictionary containing its information

def code_finder(code):  #lookup function to find events their identifier key via the event code
    code = code.upper()
    for identifier, room in rooms.items():
        if room["code"] == code:
            return identifier, room
    
    return None, None

def generate_unique_code(length):   #function for generating event codes and website URLs
    while True:
        code = ""
        for _ in range(length):
            code += random.choice(ascii_uppercase)
        
        duplicate = False

        for room in rooms.values():
            if room["code"] == code:    #checking to see if the generated code is already being used in any other event rooms
                duplicate = True
                break
        
        if not duplicate:
            break

    print("\nCode has been generated\n")
    return code

def unique_username(name, room):
    counter = 1
    unique_name = name

    while unique_name in room["names"]:
        unique_name = f"{name} ({counter})"
        counter+=1
    
    print(f"Old name: {name}\t Unique name: {unique_name}")

    return unique_name  

def haversine(lat1, lng1, lat2, lng2):  #function to calculate the approximate distance between 2 sets of coordinates
    R = 6371000  #Earth radius in meters

    #convert to radians

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlong = math.radians(lng2 - lng1)

    #haversine formula
    a = (
        math.sin(dlat / 2) ** 2 +
        math.cos(phi1) * math.cos(phi2) *
        math.sin(dlong / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    print("\nDistance calculated\n")
    return R * c  #distance in meters

def room_expiry():  #function that compares current date/time with the date/time of room creation to check if room has surpassed expiration date - if it has, room is deleted
    while True:

        expired_rooms=[]

        for identifier, room in rooms.items():
            if datetime.now() > room["expiry"]:
                expired_rooms.append(identifier)

        for identifier in expired_rooms:
            room = rooms[identifier]
            socketio.emit("room_expired", {"message": "Room has expired!"}, to=room["code"])
            del rooms[identifier]
            print(f"\nRoom {identifier} has expired and been deleted.\n")

        time.sleep(10)

@app.route("/", methods=["POST", "GET"])
def home():
    if request.method == "POST":
        #fetching user data
        name = request.form.get("name") 
        code = request.form.get("code")
        join = request.form.get("join", False)  #buttons do not have values, false is used if the user is not trying to join or enter a room
        create = request.form.get("create", False)  

        #error catching

        if not name:
            print("\nNo name\n")
            return render_template("home.html", error="Please enter a name.", code=code, name=name) #variables for name and code and passed backed to the user so they don't have to retype it after the error message
        
        session["name"] = name  #storing the host's name in the flask session

        if create != False: #if user wants to create a room, the code is generated
            print("\nProceeding to room creation\n")
            return redirect(url_for("create"))

        identifier, room = code_finder(code)

        if join != False and not code:  #if user is trying to enter the room but hasn't inputted a code
            print("\nCode not entered\n")
            return render_template("home.html", error="Please enter a room code.", code=code, name=name)
        elif room is None: #when create is false, meaning user wants to join a room, but the room isn't in the list of rooms
            print("\nRoom doesn't exist in dictionary\n")
            return render_template("home.html", error="Room does not exist.", code=code, name=name)
        else:
            print("\nJoining room\n")
            session["room_identifier"] = identifier
            return redirect(url_for("join_qr", identifier=identifier, name=name))

    return render_template("home.html")

@app.route("/create", methods=["GET", "POST"])  #route for the host to create their event and adjust room details
def create():
    if "name" not in session:
        print("\nName not in session\n")    #ensuring host has entered their name before making their event
        flash("Enter a name before creating a room")
        return redirect(url_for("home"))
    
    if request.method == "POST":
        room_name = request.form.get("room_name")   # obtaining event details from the host including GPS data
        capacity = request.form.get("capacity")
        duration = request.form.get("duration")
        lat = request.form.get("lat")
        lng = request.form.get("lng")
        accuracy=(request.form.get("accuracy") or 0)

        print(f"\nUser Coordinates: latitude={lat}, longitude={lng}, accuracy={accuracy}\n")

        if not room_name or not capacity or not duration or not lat or not lng:
            return render_template("create.html", error="Please fill in every field.", room_name=room_name, capacity=capacity, duration=duration, lat=lat, lng=lng)
        
        code = generate_unique_code(8)  #room code for joining events
        identifier = generate_unique_code(15)   #key that identifies events
        host = session.get("name")

        rooms[identifier] = {   #dictionary containing event information and chat room statistics
            "code": code,
            "members": 0,
            "names":[],
            "messages": [],
            "name": room_name,
            "host":host,
            "lat": float(lat),
            "lng": float(lng),
            "acc":float(accuracy),
            "radius": 1.0,
            "capacity": int(capacity),
            "expiry": datetime.now() + timedelta(minutes=int(duration)),
            "confirmed": False  #variable to confirm whether location details have been finalised by the user on the map page
            }

        session["room_identifier"] = identifier
        session["is_host"] = True

        return redirect(url_for("map", identifier=identifier))
    
    return render_template("create.html")

@app.route("/map/<identifier>", methods = ["GET", "POST"])  #route that shows the map of the host's event that is used to adjust the radius of the event
def map(identifier):
    if "name" not in session:
        print("\nName not in session\n")
        flash("Enter a name before creating a room")
        return redirect(url_for("home"))
    
    if identifier not in rooms:
        print("\nInvalid code\n")   #if user tries to access map page without a valid room code/identifier
        flash("Room does not exist")
        return redirect(url_for("home"))
    
    room = rooms[identifier]
    lat = room["lat"]
    lng = room["lng"]
    acc = room["acc"]
    rad = room["radius"]
    
    
    print(f"lat:{lat}, lng:{lng}, acc:{acc}, rad:{rad}")

    if request.method == "POST":
        new_lat=request.form.get("lat") #storing new coordinate data after user has adjusted their location on the map
        new_lng=request.form.get("lng")
        new_acc=request.form.get("acc")
        new_radius=request.form.get("radius")

        room["lat"] = float(new_lat)
        room["lng"] = float(new_lng)
        room["radius"] = float(new_radius)
        room["confirmed"] = True
        new_rad = room["radius"]

        print(f"\nGeolocation coordinates: latitude:{lat}, longitude:{lng}, accuracy:{acc}, old radius:{rad}\n")
        print(f"\nNew coordinates: latitude:{new_lat}, longitude:{new_lng}, accuracy:{new_acc}, new radius:{new_rad}\n")

        return redirect(url_for("qr", identifier=identifier))

    return render_template("map.html", lat=lat, lng=lng, rad=rad, acc=acc)

@app.route("/qr/<identifier>")  #route to display the QR code for the event
def qr(identifier):
    if "name" not in session:
        print("\nName not in session\n")
        flash("Enter a name before creating a room")
        return redirect(url_for("home"))
    
    if identifier not in rooms:
        print("\nInvalid code\n")
        flash("Room does not exist")
        return redirect(url_for("home"))
    
    room = rooms[identifier]

    if room["confirmed"] == False:  #ensuring the host has confirmed the event's location properly before allowing QR code generation
        print("\nLocation details not confirmed\n") 
        flash("Confirm your location before generating a QR code!")
        return redirect(url_for("map", identifier=identifier))
    
    room_name = room["name"]
    code = room["code"]
    print(room["lat"])
    print(room["lng"])
    url = url_for("join_qr",  identifier=identifier, _external=True, _scheme="https")   #url to be used to generate QR code
    return render_template("qr.html", identifier=identifier, code=code, room_name=room_name, url=url)

@app.route("/create_qr/<identifier>")   #route that creates QR code and stores it in memory for it to be sent to the browser
def create_qr(identifier):
    url = url_for("join_qr",  identifier=identifier, _external=True)
    img = qrcode.make(url)
    buffer=io.BytesIO()
    img.save(buffer, format="PNG")  #saving QR code in the buffer/memory
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")

@app.route("/join/<identifier>", methods=["GET", "POST"])   #route that contains the logic for joining a chat room
def join_qr(identifier):

    if identifier not in rooms:
        print("\nInvalid code\n")
        flash("Room does not exist")
        return redirect(url_for("home"))
    
    room = rooms[identifier]

    if room["confirmed"] == False and "name" not in session:    # for attendees joining events that haven't been properly setup yet
        print("\nRoom details not confirmed\n")
        flash("This room has not yet been set up correctly!")
        return redirect(url_for("home", identifier=identifier))
    
    if room["confirmed"] == False and "name" in session:    # for the host to let them know to setup the event properly
        print("\nRoom details not confirmed\n")
        flash("Confirm your location!")
        return redirect(url_for("map", identifier=identifier))
    
    roomAcc = room["acc"]
    roomLat=room["lat"]
    roomLng=room["lng"]
    name = session.get("name")
    user_lat = session.get("user_lat")
    user_lng = session.get("user_lng")
    user_acc = session.get("user_acc")

    if (session.get("is_host") is True and name == room["host"]):   #if the host of the event wants to join the chat room, they bypass the GPS check as their location is already verified   
        session["room_identifier"] = identifier
        new_name = unique_username(name, room)  #making sure their online username is unique
        session["name"] = new_name
        room["names"].append(new_name)
        print(room["names"])
        return redirect(url_for("room"))


    if request.method == "POST":

        # if not name:
        name = request.form.get("name") or session.get("name")
        user_lat = request.form.get("lat") or session.get("user_lat")
        user_lng = request.form.get("lng") or session.get("user_lng")
        user_acc = request.form.get("accuracy") or session.get("user_acc")
        if not user_lat:
            user_lat = request.form.get("lat")
        if not user_lng:
            user_lng = request.form.get("lng")
        if not user_acc:
            user_acc = request.form.get("accuracy")

        room = rooms[identifier]
        
        if not user_lat or not user_lng or not user_acc:
            return render_template("join.html", error="Location not available. Please enable GPS and try again.", name=name, roomLat=roomLat, roomLng=roomLng, roomAcc=roomAcc, lat=user_lat, lng=user_lng, acc=user_acc)

        user_lat = float(user_lat)
        user_lng = float(user_lng)
        user_acc = float(user_acc)
        rad=room["radius"]

        print(f"\nAttendee coordinates: latitude={user_lat}, longitude={user_lng}, accuracy={user_acc}\n")
        print(room)

        session["user_lat"] = user_lat
        session["user_lng"] = user_lng
        session["user_acc"] = user_acc

        verify_code = request.form.get("verify_code")   #if the attendee's location accuracy is poor, they must validate themselves using the room code for extra security 
        if "verify_code" in request.form:
            verify_code = verify_code.upper()

            if not verify_code:
                return render_template("join.html", error="Please enter the room code!", require_code=True, identifier=identifier, name=name)

            if verify_code == room["code"]:
                if room["members"] >= room["capacity"]:
                    print("\nRoom capacity has been reached\n")
                    return render_template("join.html", error="Sorry, the room is full!", require_code=True, identifier=identifier, name=name, roomLat=roomLat, roomLng=roomLng, roomAcc=roomAcc, lat=user_lat, lng=user_lng, acc=user_acc)
                
                session["room_identifier"] = identifier
                new_name = unique_username(name, room)
                
                session["name"] = new_name
                room["names"].append(new_name)
                print(room["names"])
                return redirect(url_for("room"))
            else:
                return render_template("join.html", error="Invalid room code", require_code=True, identifier=identifier, name=name, roomLat=roomLat, roomLng=roomLng, roomAcc=roomAcc, lat=user_lat, lng=user_lng, acc=user_acc)

        if not name:
            print("\nNo name\n")
            return render_template("join.html", error="Please enter a name.", name=name, identifier=identifier, roomLat=roomLat, roomLng=roomLng, roomAcc=roomAcc, lat=user_lat, lng=user_lng, acc=user_acc)
        
        if room["members"] >= room["capacity"]:
            print("\nRoom capacity has been reached\n")
            return render_template("join.html", error="Sorry, the room is full!", name=name, identifier=identifier, roomLat=roomLat, roomLng=roomLng, roomAcc=roomAcc, lat=user_lat, lng=user_lng, acc=user_acc)

        distance = haversine(user_lat, user_lng, room["lat"], room["lng"])  #calcuating the distance between the attendee and the venue using the haversine formula function
        demo_distance = request.args.get("demo_distance")

        if demo_distance:
            distance = float(demo_distance)

        print(f"Distance between the attendee and the host's event: {distance}\t Allowed radius: {rad}")

        lenience = min(user_acc, 1500)
        print(f"distance={distance}")
        print(f"radius={room['radius']}")
        print(f"lenience={lenience}")
        print(f"radius + lenience = {room['radius'] + lenience}")
        print(f"user_acc={user_acc}")

        if distance <= room["radius"] + 15 and user_acc <= 150:  #if the user's distance from the event is less than the event's radius, they are permitted to enter the room
            print("\nPassed radius check\n")

            if room["members"] >= room["capacity"]:
                return "Room full"
        
            session["room_identifier"] = identifier
            new_name = unique_username(name, room)
            session["name"] = new_name
            room["names"].append(new_name)
            print(room["names"])

            return redirect(url_for("room"))
        
        elif distance <= room["radius"] + lenience and user_acc > 150:  #if the user's accuracy is poor, they have to validate themselves with the room code
            print("\nVerify with code\n")
            session["name"] = name
            session["distance"] = distance
            
            return render_template("join.html", name=name, require_code=True, identifier=identifier, roomAcc=roomAcc, roomLat=roomLat, roomLng=roomLng, lat=user_lat, lng=user_lng, acc=user_acc, distance=distance)

        else:
            print("\nFailed radius check\n")
            return render_template("join.html", error="Sorry, you are out of bounds for this event!", identifier=identifier, name=name, roomAcc=roomAcc, roomLat=roomLat, roomLng=roomLng, lat=user_lat, lng=user_lng, acc=user_acc, distance=distance)
    
    return render_template("join.html", identifier=identifier, roomAcc=roomAcc, name=name, roomLat=roomLat, roomLng=roomLng)

@app.route("/room")
def room():
    identifier = session.get("room_identifier")

    if session.get("name") is None:    #ensures that the room page can only be accessed after entering a room code or creating a new room
        print("\nName not in session\n")
        flash("Enter a name before joining a room")
        return redirect(url_for("home"))
    
    if identifier is None or identifier not in rooms:
        print("\nInvalid/empty code\n")
        flash("Please enter a valid code")
        return redirect(url_for("home"))

    room = rooms[identifier]
    room_name=room["name"]
    code=room["code"]
    lat=room["lat"]
    lng=room["lng"]
    rad=room["radius"]
    distance = session.get("distance")
    
    return render_template("room.html", identifier=identifier, code=code, messages=room["messages"], name=room_name, lat=lat, lng=lng, rad=rad, distance=distance)

@socketio.on("message")     #socketio function that creates a live message
def message(data):
    identifier = session.get("room_identifier")
    if identifier not in rooms:
        return
    room = rooms[identifier]
    code = room["code"]
    content = {
        "name": session.get("name"),
        "message": data["data"],
        "is_host": session.get("name") == room["host"]
    }
    send(content, to=code)
    room["messages"].append(content)
    print(f"\n{session.get('name')} said: {data['data']}\n")
    print(room["messages"])

@socketio.on("connect")
def connect(auth):
    identifier = session.get("room_identifier")
    name = session.get("name")
    room = rooms[identifier]
    code = room["code"]

    if not identifier or not name:
        return
        
    if identifier not in rooms:   #if they are inside a room for their session but it is not a valid room in our list of rooms
        leave_room(code)
        return
    
    join_room(code) #socket function to join room
    send({"name": name, "message": "has entered the room", "is_host": name == room["host"]}, to=code)    #sending a message in the chat room when a user has joined the room
    room["members"] += 1 #incrementing the room capacity number by 1 to keep track of how many people are present in the room
    print(f"\n{name} joined room {code}\n") # debug statement to verify user joined the room
    print(room["messages"])

@socketio.on("disconnect")  #socket function for leaving an event chat room
def disconnect():
    identifier = session.get("room_identifier")
    name = session.get("name")
    room = rooms[identifier]
    code = room["code"]
    leave_room(code)

    if identifier in rooms:
        room["members"] -=1 
        # if rooms[room]["members"] <= 0:
        #     del rooms[room] #deleting the room once there are no more users in the room

    send({"name": name, "message": "has left the room", "is_host": name == room["host"]},  to=code)
    print(f"\n{name} left room {code}\n")
    print(room["messages"])

@socketio.on("remove")  #socket function for when an attendee is kicked from the room for being too far away from the event
def remove():
    identifier = session.get("room_identifier")
    name = session.get("name")
    room = rooms[identifier]
    code = room["code"]

    if identifier in rooms:
        leave_room(code)
        room["members"] -=1 
        
        emit("removed", {
            "message": "You have been removed for leaving the bounds of the event."
        })

        send({"name":"System", "message": f"{name} was removed for leaving the bounds of the event.", "is_host": name == room["host"]}, to=code)

    session.pop("room_identifier", None)

if __name__ == "__main__":
    tunnel = ngrok.connect(5000)
    public_url = (tunnel.public_url.replace("http://", "https://"))
    print("\nNGROK LINK:", public_url, "\n")    #hosting on ngrok to allow others to access the web app via a url
    socketio.start_background_task(room_expiry) #background task that runs a function to check when chat rooms should expire
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)