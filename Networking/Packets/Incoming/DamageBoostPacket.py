from Networking.Packets.Packet import Packet

# Field layout is unknown - RealmShark (the reference packet dissector) also
# treats this as an opaque 8-byte payload with no known breakdown. Stored raw
# so the wire format is preserved byte-for-byte on re-encode.
class DamageBoostPacket(Packet):
    def __init__(self):
        self.type = "DAMAGEBOOST"
        self.unknownBytes = b"\x00" * 8

    def read(self, reader):
        self.unknownBytes = reader.readRawBytes(8)

    def write(self, writer):
        writer.writeRawBytes(self.unknownBytes)
