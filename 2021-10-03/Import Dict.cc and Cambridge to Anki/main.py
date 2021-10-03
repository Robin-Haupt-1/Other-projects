import datetime
from aqt.qt import QAction
from aqt.utils import showInfo, tooltip

from .constants import *
from .utils import *
from .edit_words_dialog import EditNewWordsDialog
from aqt import mw
from aqt import gui_hooks
from datetime import datetime
from .utils import all_imported_words
from anki.consts import *



class ImportEwFromCambridge:
    def __init__(self):
        # Initialize instances
        self.cambridge_dict = None  # html of cambridge pages
        self.words = None  # words after user has corrected them
        self.scrubbing = None  # dict of unique words and user corrected scrubbed version
        self.done = all_imported_words()  # the ew that have previously been imported
        self.new: [str] = []  # the ew that will be imported in this run

        # read new ew
        with os.scandir(EW_FOLDER) as files:
            files=[file for file in files]
            files = sorted(files, key=lambda x: x.name)

            words = [open(file.path, "r", encoding="utf-8").read() for file in files]
            [self.new.append(word) for word in words if word not in self.done]

            [log(f"already imported: {word}", color="red") for word in words if word in self.done]

        # show to user to clean them into matching patterns (using Qt Dialog with TextBox)

        self.edit_dialog = EditNewWordsDialog(self, "\n".join(self.new))
        self.edit_dialog.show()
        self.edit_dialog.exec()

    def scrubbing_edited(self, words, scrubbing, cambridge_dict):
        """receive dict of unique words and their corrected scrubbed version and a dict containing the html of cambridge page for each scrubbed term
        :param words:
        """
        self.scrubbing = scrubbing
        self.cambridge_dict = cambridge_dict
        self.words = words

        self.create_cards()

    def create_cards(self):
        log("Creating cards")
        # sort cards into groups
        grouped_words: {[str]} = {}

        for word in self.words:

            english, german = (x.strip() for x in word.split("\t"))
            if english in grouped_words:
                grouped_words[english].append(german)
            else:
                grouped_words[english] = [german]


        for english, german in grouped_words.items():
            log(f"Importing {english} - {german}")

            scrubbed = self.scrubbing[english]

            prevalence = int(get_phrasefinder(scrubbed) / 1000)
            fields = {"Englisch": english, "Bild": "", "Audio": "", "IPA": "", "Häufigkeit": str(prevalence).zfill(6), "Englisch scrubbed": scrubbed}

            # Assign german words to their fields
            for i, x in enumerate(german[:10]):
                fields[f"Deutsch {str(i + 1)}"] = x

            # Wait till theres an internet connection to continue
            wait_for_internet_connection()

            # Download audio from Cambridge
            # check if there are any results for the word (if not, scrubbing[english] will be "False"
            # todo: detect if there is ipa but no audio (results in absurd url now)
            if html := self.cambridge_dict[scrubbed]:
                # Extract american pronunciation and IPA
                if any(html.find(x) == -1 for x in ["us dpron-i", 'type="audio/ogg" src="', '<span class="ipa dipa lpr-2 lpl-1">']):
                    log("Does not have audio or IPA information!")
                else:
                    american_part = html[html.find("us dpron-i"):]
                    audio_url = american_part[american_part.find('type="audio/ogg" src="') + len('type="audio/ogg" src="'):]
                    audio_url = "https://dictionary.cambridge.org" + audio_url[:audio_url.find('"/>')]
                    ipa = american_part[american_part.find('<span class="ipa dipa lpr-2 lpl-1">'):american_part.find("/</span></span>")]

                    try:
                        audio_path = os.path.join(MEDIA_FOLDER, f"cambridge-{scrubbed}.ogg")
                        with open(audio_path, "wb") as file:
                            file.write(load_url(audio_url, True).content)
                            fields["Audio"] = f'[sound:cambridge-{scrubbed}.ogg]'

                    except Exception as e:
                        print(e)

                    # Set field values
                    fields["IPA"] = ipa

            else:
                log(f"No Cambridge definition found for {scrubbed} ({english}).", color="red")

            # Create the new notes
            # Set the right deck (according to how common the word is) and model
            selected_deck_id = mw.col.decks.id("All::Audio::Sprachen::🇺🇸 Englisch::_New" if prevalence >= 100 else "All::Audio::Sprachen::🇺🇸 Englisch::_New (rare)")
            mw.col.decks.select(selected_deck_id)
            model = mw.col.models.by_name(NOTE_TYPE_NAME)
            deck = mw.col.decks.get(selected_deck_id)
            deck['mid'] = model['id']
            mw.col.decks.save(deck)
            model['did'] = selected_deck_id
            mw.col.models.save(model)

            note = mw.col.newNote()
            for (name, value) in note.items():
                if name in fields:
                    note[name] = fields[name]
            mw.col.addNote(note)
            for card in note.cards():
                card.queue = anki.consts.QUEUE_TYPE_SUSPENDED
                card.flush()

        tooltip("All words imported!")
        log("All words imported!", color="green")

        # Save a list of all the words that have just been imported
        with open(os.path.join(DONE_FOLDER, f"{datetime.now().strftime('%Y-%m-%d %H-%M-%S imported.txt')}"), "w+", encoding="utf-8") as file:
            file.write("\n".join(self.new))

        # Refresh the list of all imported words that the tampermonkey script reads
        update_tampermonkey_list()

        # empty the folder that holds the crawled words before they get imported
        [os.remove(file.path) for file in os.scandir(EW_FOLDER)]
