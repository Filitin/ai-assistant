from pycaw.utils import AudioUtilities

devices = AudioUtilities.GetAllDevices()

for device in devices:
    print(f"ID: {device.id}")
    print(f"Имя: {device.FriendlyName}")
    print(f"Состояние: {device.state}")
    print("---")
    