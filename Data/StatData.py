from Constants.StatTypes import StatTypes, nameOf

class StatData:
    def __init__(self, statType=0, statValue=0, strStatValue="", secondaryValue=0):
        self.statType = statType
        self.statValue = statValue
        self.strStatValue = strStatValue
        self.secondaryValue = secondaryValue

    def isStringStat(self):
        return self.statType in [StatTypes.EXPSTAT, StatTypes.NAMESTAT, StatTypes.ACCOUNTIDSTAT, StatTypes.GUILDNAMESTAT,
                                StatTypes.PETNAMESTAT, StatTypes.GRAVEACCOUNTID, StatTypes.OWNERACCOUNTIDSTAT,
                                StatTypes.UNIQUEDATASTRING, StatTypes.MODIFIERSSTAT, StatTypes.MATERIALSTAT, StatTypes.CRUCIBLESTAT,
                                StatTypes.DUSTSTAT, StatTypes.DUSTAMOUNTSTAT, StatTypes.MATERIALCAPSTAT, StatTypes.BLOODRITUALSTAT]

    def statToName(self, statType=None):
        if statType is None:
            return nameOf(self.statType)
        else:
            return nameOf(statType)   

    def read(self, reader):
        self.statType = reader.readUnsignedByte()
        if self.isStringStat():
            self.strStatValue = reader.readStr()
        else:
            self.statValue = reader.readCompressedInt()
        self.secondaryValue = reader.readCompressedInt()

    def write(self, writer):
        writer.writeUnsignedByte(self.statType)
        if self.isStringStat():
            writer.writeStr(self.strStatValue)
        else:
            writer.writeCompressedInt(self.statValue)
        writer.writeCompressedInt(self.secondaryValue)

    def clone(self):
        return StatData(self.statType, self.statValue, self.strStatValue, self.secondaryValue)

    def __str__(self):
        # Named stat first (falls back to the raw number if unknown) - makes
        # full packet logging (Networking/Listener.py, Networking/Sender.py)
        # directly greppable by name (e.g. "CONDITIONSTAT") instead of
        # needing a StatTypes.py lookup by hand for every number.
        name = self.statToName() or str(self.statType)
        if self.isStringStat():
            return "{} ({}): strStatValue={}, secondaryValue={}".format(name, self.statType, self.strStatValue, self.secondaryValue)
        else:
            return "{} ({}): statValue={}, secondaryValue={}".format(name, self.statType, self.statValue, self.secondaryValue)

    def __repr__(self):
        return str(self)

