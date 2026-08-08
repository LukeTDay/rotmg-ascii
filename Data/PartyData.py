from Networking.Reader import Reader

class PartyData:
    def __init__(self):
        self.description = ""
        self.party_id = 0
        self.powerlevel = 0
        self.current_players = 0
        self.max_players = 0
        self.party_type = 0
        self.privacy = 0
        self.required_maxed_stats = 0
        self.server = 0

    def read(self, reader: Reader):
        # Order must match Java exactly
        self.description = reader.readStr()
        self.party_id = reader.readInt32()
        self.powerlevel = reader.readShort()
        self.current_players = reader.readByte()
        self.max_players = reader.readByte()
        self.party_type = reader.readByte()
        self.privacy = reader.readByte()
        self.required_maxed_stats = reader.readByte()
        self.server = reader.readByte()

    def write(self, writer):
        writer.writeStr(self.description)
        writer.writeInt32(self.party_id)
        writer.writeShort(self.powerlevel)
        writer.writeByte(self.current_players)
        writer.writeByte(self.max_players)
        writer.writeByte(self.party_type)
        writer.writeByte(self.privacy)
        writer.writeByte(self.required_maxed_stats)
        writer.writeByte(self.server)
