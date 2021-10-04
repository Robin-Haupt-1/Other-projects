from aqt.qt import QDialog, QGridLayout, QTextEdit, QScrollBar, QPushButton
from PyQt5.QtGui import QCloseEvent, QFont, QTextBlockFormat, QTextCursor
from PyQt5.QtCore import Qt
from PyQt5 import QtGui
from aqt.utils import showInfo
from .utils import scrub_word, load_url, wait_for_internet_connection, log, get_phrasefinder
from aqt import mw
from .constants import *
from math import ceil

numbers = "\n".join([str(x) for x in range(100)])


class EditNewWordsDialog(QDialog):
    def __init__(self, parent_class, words):
        words = words.replace("\t", EDIT_WORDS_SEPERATOR)
        super(EditNewWordsDialog, self).__init__()
        self.parent = parent_class

        # set up font
        font = QFont()
        font.setPointSize(14)

        # Textedit indicating how the program groups words based on their english side. To help with refactoring them into appropriate groups
        self.word_groups = QTextEdit()
        self.word_groups.setLineWrapMode(QTextEdit.NoWrap)
        self.word_groups.setMaximumWidth(40)
        self.word_groups.setText(numbers)
        self.word_groups.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.word_groups.setFont(font)
        self.word_groups.setEnabled(False)

        # Textedit with new english and german words, seperated by ~
        self.new_words = QTextEdit()
        self.new_words.setLineWrapMode(QTextEdit.NoWrap)
        self.new_words.setText(words)
        self.new_words.textChanged.connect(self.words_changed)
        self.new_words.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.sb: QScrollBar = self.new_words.verticalScrollBar()
        self.sb.valueChanged.connect(lambda pos: self.word_groups.verticalScrollBar().setValue(pos))
        self.new_words.setFont(font)
        self.words_changed()

        # Done editing button
        self.done_button = QPushButton()
        self.done_button.setText("Done editing")
        self.done_button.clicked.connect(self.done_)

        # Set up layout
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.addWidget(self.word_groups, 0, 0)
        grid.addWidget(self.new_words, 0, 1)
        grid.addWidget(self.done_button, 1, 1)
        self.setLayout(grid)
        self.setWindowTitle('Edit new words')
        self.setMinimumWidth(1200)
        self.setMinimumHeight(1000)
        sb = self.new_words.verticalScrollBar()
        sb.setValue(sb.maximum())

    def get_words(self):
        return self.new_words.toPlainText().strip()

    def words_changed(self, *args):
        """rebuild the word_groups textedit"""

        # extract all unique english words and assign them a number
        word_groups = {}  # all unique words as keys, their number as values
        english_words = [word.split(EDIT_WORDS_SEPERATOR_BASIC)[0].strip() for word in self.get_words().split("\n")]

        for english_word in english_words:
            if english_word not in word_groups:
                word_groups[english_word] = len(word_groups.keys()) + 1

        word_group_content = "\n".join(["----" if x % 2 == 0 else "////" for x in [word_groups[y] for y in english_words]])
        self.word_groups.setText(word_group_content)

        self.word_groups.verticalScrollBar().setValue(self.sb.value())

    def done_(self):
        """pass unique words on to user to verify automated scrubbing output"""
        self.close()
        # replace ~ and any surrounding whitespace with tabs again
        words_with_tab = [w.split(EDIT_WORDS_SEPERATOR_BASIC)[0].strip() + "\t" + w.split(EDIT_WORDS_SEPERATOR_BASIC)[1].strip() for w in self.get_words().split("\n")]
        words = [x.split(EDIT_WORDS_SEPERATOR_BASIC)[0].strip() for x in self.get_words().split("\n")]
        # remove duplicates this way instead of using set() to preserve order
        unique_words = []
        [unique_words.append(x) for x in words if x not in unique_words]

        # show dialog to allow user to correct the scrubbing
        correct_scrubbed_output_dialog = CorrectScrubbingOutput(self.parent, words_with_tab, unique_words)
        correct_scrubbed_output_dialog.show()
        correct_scrubbed_output_dialog.exec()


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Correct Scrubbing Window


class CorrectScrubbingOutput(QDialog):
    def __init__(self, parent_class, words_with_tabs: [str], unique_words: [str]):
        """
        :param words_with_tabs: list of words with english and german value seperated by tabs
        :param unique_words: list of all unique english words
        """
        super(CorrectScrubbingOutput, self).__init__()
        self.words_with_tabs = words_with_tabs
        self.unique_words = unique_words
        self.parent = parent_class

        self.scrubbed_words = [scrub_word(x) for x in self.unique_words]
        self.cambridge_available_cache = {}  # for every scrubbed term, contains either the cambridge html or 'false' if term can't be found on cambridge
        self.phrasefinder_cache = {}
        self.look_up_scrubbed_timer = None  # timer to look up newly entered corrected versions of scrubbed terms on cambridge dictionary. timeout so as to not make the program freeze after every keystroke.

        # Set up font for textedits
        font = QFont()
        font.setPointSize(14)

        # Textedit containing original, full-length terms
        self.original_words = QTextEdit()
        self.original_words.setLineWrapMode(QTextEdit.NoWrap)
        self.original_words.setMaximumWidth(250)
        self.original_words.setText("\n".join(self.unique_words))
        self.original_words.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.original_words.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.original_words.setFont(font)
        self.original_words.setEnabled(False)

        # Textedit containing the automatically scrubbed version of the original words and allowing user to edit them
        self.scrubbed = QTextEdit()
        self.scrubbed.setLineWrapMode(QTextEdit.NoWrap)
        self.scrubbed.setMinimumWidth(250)
        self.scrubbed.setText(("\n".join(self.scrubbed_words)))
        self.scrubbed.verticalScrollBar().valueChanged.connect(self.on_scroll)
        self.scrubbed.setFont(font)
        self.scrubbed.textChanged.connect(self.scrubbed_changed)

        # Textedit indicating whether the term can be found on cambridge dictionary (blank line if yes, otherwise 'XX')
        self.cambridge_ipa = QTextEdit()
        self.cambridge_ipa.setLineWrapMode(QTextEdit.NoWrap)
        self.cambridge_ipa.setMinimumWidth(250)
        self.cambridge_ipa.setText("")
        self.cambridge_ipa.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cambridge_ipa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cambridge_ipa.setFont(font)
        self.cambridge_ipa.setEnabled(False)

        # Textedit showing how often the term occurs in the phrasefinder corpus
        self.phrasefinder_rank = QTextEdit()
        self.phrasefinder_rank.setLineWrapMode(QTextEdit.NoWrap)
        self.phrasefinder_rank.setMaximumWidth(100)
        self.phrasefinder_rank.setAlignment(Qt.AlignRight)
        self.phrasefinder_rank.setText("")
        self.phrasefinder_rank.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.phrasefinder_rank.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.phrasefinder_rank.setFont(font)
        self.phrasefinder_rank.setEnabled(False)

        # button to finish editing and create cards
        self.done_button = QPushButton()
        self.done_button.setText("Done editing")
        self.done_button.clicked.connect(self.done_)

        # set line height on all textedits

        [self.set_line_height(x) for x in [self.original_words, self.phrasefinder_rank, self.cambridge_ipa, self.scrubbed]]

        # Set up layout
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.addWidget(self.original_words, 0, 0)
        grid.addWidget(self.scrubbed, 0, 1)
        grid.addWidget(self.cambridge_ipa, 0, 2)
        grid.addWidget(self.phrasefinder_rank, 0, 3)
        grid.addWidget(self.done_button, 1, 1)
        self.setLayout(grid)
        self.setWindowTitle('Edit scrubbing output')
        self.setMinimumWidth(500)
        self.setMinimumHeight(1000)
        self.look_up_scrubbed()

        self.triage()

    def on_scroll(self, position):
        """adjust the scroll position of cambridge_available and original_words to keep synchronized with 'scrubbed' textedit"""
        self.original_words.verticalScrollBar().setValue(position)
        self.cambridge_ipa.verticalScrollBar().setValue(position)
        self.phrasefinder_rank.verticalScrollBar().setValue(position)

    def triage(self):
        """put the words that need the most attention to the top of the list"""

    def scrubbed_changed(self):
        """Whenever user edits scrubbed terms, (re)start timer to look them up in 0.7 seconds"""
        if self.look_up_scrubbed_timer:
            self.look_up_scrubbed_timer.stop()
        self.look_up_scrubbed_timer = mw.progress.timer(700, self.look_up_scrubbed, False)

    def look_up_scrubbed(self, *args):
        """Look up all new scrubbed terms on cambridge dictionary and phrasefinder website. store results in cache variables"""

        scrubbed = [x.strip() for x in self.scrubbed.toPlainText().strip().split("\n")]

        for s in scrubbed:
            # look up on cambridge all terms that haven't yet been looked up
            if s not in self.cambridge_available_cache:

                log(f"looking up '{s}' on cambridge dictionary...", end="\t")
                html = load_url('https://dictionary.cambridge.org/de/worterbuch/englisch/' + s, True).text

                # check if there are any results for the word by looking for phrase contained in 'no results' page
                if "Die beliebtesten Suchbegriffe" not in html:
                    self.cambridge_available_cache[s] = html
                    log("found", color="green", start="")
                else:
                    self.cambridge_available_cache[s] = False
                    log("not found", color="red", start="")

            if s not in self.phrasefinder_cache:
                # look up on phrasefinder

                log(f"looking up '{s}' on phrasefinder...", end="\t")
                i = get_phrasefinder(s)

                self.phrasefinder_cache[s] = i
                log(f"{i} occurences", color="green", start="")

        # rebuild the cambridge_available textedit content
        self.cambridge_ipa.setText("<br>".join([self.get_ipa(s) if s in self.cambridge_available_cache and self.cambridge_available_cache[s] else "XX" for s in scrubbed]))

        # rebuild the phrasefinder_rank textedit content
        self.phrasefinder_rank.setText("\n".join([str(int(ceil(self.phrasefinder_cache[s] / 1000))).rjust(6) for s in scrubbed]))

        # scroll all textedits to the correct position again
        self.on_scroll(self.scrubbed.verticalScrollBar().value())

        # set both 'indicator' textedits to the corrent line spacing
        self.set_line_height(self.phrasefinder_rank)
        self.set_line_height(self.cambridge_ipa, 115)

    def set_line_height(self, textedit: QTextEdit, height: int = 120):
        """Set the line height of given QTextEdit by merging it with a QTextBlockFormat"""
        # Reference: https://stackoverflow.com/questions/10250533/set-line-spacing-in-qtextedit

        blockFmt = QTextBlockFormat()
        blockFmt.setLineHeight(height, QTextBlockFormat.ProportionalHeight)
        theCursor = textedit.textCursor()
        theCursor.clearSelection()
        theCursor.select(QTextCursor.Document)
        theCursor.mergeBlockFormat(blockFmt)

    def get_ipa(self, word: str):
        html = self.cambridge_available_cache[word]
        if any(html.find(x) == -1 for x in ["us dpron-i", 'type="audio/ogg" src="', '<span class="ipa dipa lpr-2 lpl-1">']):
            return "XXX"
        else:
            american_part = html[html.find("us dpron-i"):]
            return american_part[american_part.find('<span class="ipa dipa lpr-2 lpl-1">'):american_part.find("/</span></span>")]

    def done_(self):
        """Extract original words and corrected scrubbed versions and return them to parent class to create Anki cards"""
        self.close()
        original = [x.strip() for x in self.original_words.toPlainText().split("\n")]
        scrubbed = [x.strip() for x in self.scrubbed.toPlainText().split("\n")]
        self.parent.scrubbing_edited(self.words_with_tabs, dict([(original[x], scrubbed[x]) for x in range(len(original))]), self.cambridge_available_cache)
