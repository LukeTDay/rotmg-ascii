
class CharData:
    def __init__(self):
        self.charIds = []
        self.currentCharId = -1
        self.nextCharId = -1
        self.maxNumChars = -1
        # classId -> BestLevel reached (char_list.xml Account/Stats/ClassStats) -
        # a class absent here has never been made, i.e. level 0.
        self.classBestLevels: dict[int, int] = {}
        # classIds unlocked per Constants/ClassIds.CLASS_UNLOCK_REQUIREMENTS.
        self.unlockedClasses: set[int] = set()
        # <Account>/<TDone> presence (char_list.xml) - confirmed 2026-08-11 by
        # diffing two real accounts: present (self-closing) once the tutorial's
        # been completed, absent entirely otherwise. Defaults True (assume done)
        # so a parse failure fails toward nexus, not toward forcing tutorial.
        self.tutorialDone: bool = True

