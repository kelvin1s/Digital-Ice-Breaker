#Testing the location verification logic
def verify(distance, radius, accuracy):
        lenience = min(accuracy, 1500)

        if distance <= radius + 15 and accuracy <= 150:
                return "Accepted"
        elif distance <= radius + lenience and accuracy > 150:
                return "Validate with room code"
        else:
                return "Rejected"
        
# Test cases where the room has a 100m wide radius        
tests = [
    # distance, accuracy, expected result
    (0, 5, "Accepted"),
    (50, 5, "Accepted"),
    (115, 50, "Accepted"),
    (116, 50, "Rejected"),
    (116, 150, "Rejected"),
    (116, 151, "Validate with room code"),
    (251, 151, "Validate with room code"),
    (252, 151, "Rejected"),
    (1600,1500, "Validate with room code")
]
for distance, accuracy, expected in tests:
        actual = verify(distance, 100, accuracy)
        if actual == expected:
                result = "PASS"
        else:
                result = "FAIL"

        print(f"{result} | "f"Distance:{distance}m | "f"Accuracy:{accuracy}m | "f"Expected:{expected} | " f"Actual: {actual}")