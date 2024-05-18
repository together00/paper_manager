#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
ANGRYsearch - file search, instant results as you typeself.

Attempt of making multiplatform version of Everything Search Engine
https://www.voidtools.com/
"""

# Hide docstring warnings
# Ignore imported but not used
# Hide warning function is too complex
# pylama:ignore=D100,D101,D102,D103,D105,W0611,C901

import base64
import locale
import mimetypes
import os
import platform
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time

from datetime import datetime
from itertools import permutations
from operator import itemgetter
from os.path import join as join_path

import PyQt5.QtCore as Qc
import PyQt5.QtGui as Qg
import PyQt5.QtWidgets as Qw

# THE DATABASE WAS BUILD USING FTS5 EXTENSION OF SQLITE3
FTS5_AVAILABLE = True

# CONFIG AND DATABASE PATHS
TEMP_PATH = Qc.QStandardPaths.standardLocations(
    Qc.QStandardPaths.TempLocation)[0]
CACHE_PATH = Qc.QStandardPaths.standardLocations(
    Qc.QStandardPaths.CacheLocation)[0]
CONFIG_PATH = Qc.QStandardPaths.standardLocations(
    Qc.QStandardPaths.ConfigLocation)[0] + '/angrysearch/angrysearch.conf'
DATABASE_PATH = join_path(os.path.expanduser('~'),
                          CACHE_PATH,
                          'angrysearch',
                          'angry_database.db')

# Modify the dataset path
database_dir = '/home/moon/.cache/angrysearch/'
# 2023-01-14
database_dir2 = '/home/moon/data/notes/code/database/'

def run_query(query, parameters=()):
    con = sqlite3.connect(database_dir + 'angry_database.db')
    query_result = con.execute(query, parameters)
    con.close
    return query_result

def run_update(query, parameters=()):
    con = sqlite3.connect(database_dir + 'angry_database.db')
    con.execute(query, parameters)
    con.commit()
    con.close

def run_update_metadata(query, parameters=()):
    con = sqlite3.connect(database_dir2 + 'metadata.db')
    con.execute(query, parameters)
    con.commit()
    con.close

def run_query_metadata(query, parameters=()):
    con = sqlite3.connect(database_dir2 + 'metadata.db')
    query_result = con.execute(query, parameters)
    con.close
    return query_result

# THREAD FOR ASYNC SEARCHES IN THE DATABASE
# RETURNS FIRST 500(number_of_results) RESULTS MATCHING THE QUERY
# fts VALUE DECIDES IF USE FAST "MATCH" OR SLOWER BUT SUBSTRING AWARE "LIKE"
class ThreadDBQuery(Qc.QThread):
    db_query_signal = Qc.pyqtSignal(str, list, list)

    def __init__(self, db_query, db_query_attribute, setting_params, parent=None):
        super().__init__()
        self.words_quoted = None
        self.number_of_results = setting_params['number_of_results']
        self.fts = setting_params['fts']
        self.regex_mode = setting_params['regex_mode']
        self.db_query = db_query
        
        # MOON, 2024-01-01
        self.db_query_attribute = db_query_attribute

    def run(self):
        """Run user's search query"""

        if self.regex_mode:
            q = "SELECT * FROM angry_table WHERE path REGEXP ? LIMIT ?"
            params = (self.db_query, self.number_of_results)
        elif self.fts:
            sql_query = self.match_query_adjustment(self.db_query)
            # MOON, 2024-01-01
            q = "SELECT * FROM angry_table WHERE {} MATCH ? LIMIT ?".format(self.db_query_attribute)
            params = (sql_query, self.number_of_results)
        else:
            sql_query = self.like_query_adjustment(self.db_query)
            q = "SELECT * FROM angry_table WHERE path LIKE ? LIMIT ?"
            params = (sql_query, self.number_of_results)

        db_query_result = run_query(q, params).fetchall()
        self.db_query_signal.emit(self.db_query,
                                  db_query_result,
                                  self.words_quoted)

    # FTS CHECKBOX IS UNCHECKED, SO NO INDEXING
    # PERMUTATION OF INPUT PHRASES IS USED SO THAT ORDER DOES NOT MATTER
    def like_query_adjustment(self, input_text):
        input_text = input_text.replace('"', '""')

        o = []
        p = permutations(input_text.strip().split())
        for x in p:
            o.append('"%{0}%"'.format('%'.join(x)))

        return ' OR path LIKE '.join(o)

    # FTS CHECKBOX IS CHECKED, FTS VIRTUAL TABLES ARE USED
    def match_query_adjustment(self, input_text):
        for x in {'\\', '?', '(', ')', '*'}:
            if x in input_text:
                input_text = input_text.replace(x, '')

        query_words = input_text.strip().split()

        if FTS5_AVAILABLE:
            # MINUS SIGN MARKS PHRASES THAT MUST NOT APPEAR IN RESULTS
            words_no_minus = []
            excluded_words = []
            for x in query_words:
                if x.startswith('-'):
                    if len(x) > 1:
                        excluded_words.append(x[1:])
                else:
                    words_no_minus.append(x)

            if not words_no_minus:
                words_no_minus.append('1')

            # QUOTED PHRASES ARE SEARCHED WITHOUT WILD CARD * AT THE END
            final_query = ''
            words_quoted = []
            for x in words_no_minus:
                if '\"' in x:
                    if x.startswith('\"') and x.endswith('\"'):
                        x = x.replace('\"', '')
                        final_query += '"{}" '.format(x)
                        words_quoted.append(x)
                        continue
                    x = x.replace('\"', '')
                if '\'' in x:
                    if x.startswith('\'') and x.endswith('\''):
                        x = x.replace('\'', '')
                        final_query += '"{}" '.format(x)
                        words_quoted.append(x)
                        continue
                    x = x.replace('\'', '')
                final_query += '"{}"* '.format(x)

            if len(excluded_words) > 0:
                exclude_query_part = ''
                for x in excluded_words:
                    x_is_quoted = False
                    if '\"' in x:
                        if x.startswith('\"') and x.endswith('\"'):
                            x_is_quoted = True
                        x = x.replace('\"', '')
                    if '\'' in x:
                        if x.startswith('\'') and x.endswith('\''):
                            x_is_quoted = True
                        x = x.replace('\'', '')
                    if x_is_quoted:
                        if len(x) > 1:
                            exclude_query_part += 'NOT {} '.format(x)
                    else:
                        exclude_query_part += 'NOT {}* '.format(x)

                final_query = '{} {}'.format(final_query,
                                             exclude_query_part)

            self.words_quoted = words_quoted
            return final_query

        if not FTS5_AVAILABLE:
            final_query = ''
            words_quoted = []
            for x in query_words:
                if '\"' in x:
                    if x.startswith('\"') and x.endswith('\"'):
                        x = x.replace('\"', '')
                        final_query += '"{}" '.format(x)
                        words_quoted.append(x)
                        continue
                    x = x.replace('\"', '')
                if '\'' in x:
                    if x.startswith('\'') and x.endswith('\''):
                        x = x.replace('\'', '')
                        final_query += '"{}" '.format(x)
                        words_quoted.append(x)
                        continue
                    x = x.replace('\'', '')

                final_query += '{}* '.format(x)

            self.words_quoted = words_quoted
            return final_query


# THREAD FOR PREVENTING DATABASE QUERY BEING DONE ON EVERY SINGLE KEYPRESS
# SHORT WAIT TIME LETS USER FINISH TYPING, OFF BY DEFAULT
class ThreadDelayDBQuery(Qc.QThread):
    delay_signal = Qc.pyqtSignal(str)

    def __init__(self, input_text, parent=None):
        super().__init__()
        self.input_text = input_text

    def run(self):
        time.sleep(0.2)
        self.delay_signal.emit(self.input_text)


# THREAD FOR UPDATING THE DATABASE
# PREVENTS LOCKING UP THE GUI AND ALLOWS TO SHOW PROGRESS
# NEW DATABASE IS CREATED IN /tmp AND REPLACES ONE IN /.cache/angrysearch
class ThreadDBUpdate(Qc.QThread):
    db_update_signal = Qc.pyqtSignal(str, str)
    crawl_signal = Qc.pyqtSignal(str)

    def __init__(self, lite, dirs_excluded, parent=None):
        super().__init__()
        self.lite = lite
        self.table = []
        self.prep_excluded = []
        self.crawl_time = ''
        self.database_time = ''

        for x in dirs_excluded:
            y = [k.encode() for k in x.split('/') if k]
            z = ''

            # IF FULL PATH
            if x.startswith('/'):
                up = b'/' + b'/'.join(y[:-1])
                z = {'case': 1, 'ign': y[-1], 'up': up}
            # IF ONLY SINGLE DIRECTORY NAME
            elif len(y) == 1:
                z = {'case': 2, 'ign': y[-1], 'up': ''}
            # IF PARENT/TARGET
            elif len(y) == 2:
                z = {'case': 3, 'ign': y[-1], 'up': y[-2]}

            if z:
                self.prep_excluded.append(z)

        self.directories_timestamp = {}

    def run(self):
        self.db_update_signal.emit('label_1', '0')
        self.crawling_drives()

        self.db_update_signal.emit('label_2', self.crawl_time)
        self.new_database()

        self.db_update_signal.emit('label_3', self.database_time)
        self.replace_old_db_with_new()

        self.db_update_signal.emit('the_end_of_the_update', '0')
    
    # To exclude some files that are not paper according to the filename. MOON 2023-12-31
    def check_paper_name(self, fname):
        paperfname = fname.decode(encoding='utf-8', errors='ignore')
        if paperfname.endswith('.pdf') == False:
            return False
        if ' ' not in paperfname or '_' in paperfname:
            return False
        # count_upper = sum(1 for char in paperfname if char.isupper())
        # # I think there is no paper who has only two upper characters, MOON 2024-01-08
        # if count_upper <= 2:
        #     return False
        return paperfname[:-4]

    def crawling_drives(self):
        def error(err):
            print(err)

        # MOON, 2024-01-06, the folders used to save papers
        root_dirs = [b'/home/moon/data/mine/', b'/home/moon/data/papers/']
        tstart = datetime.now()

        dir_list = []
        file_list = []

        try:
            # SCANDIR ALLOWS MUCH FASTER INDEXING OF THE FILE SYSTEM, OBVIOUS
            # IN LITE MODE IS NOW PART OF PYTHON 3.5, FUNCTIONALLY
            # REPLACING os.walk
            import scandir
        except ImportError:
            scandir = os

        for root_dir in root_dirs:
            for root, dirs, files in scandir.walk(root_dir, onerror=error):
                dirs.sort()
                files.sort()

                if root == b'/' and b'proc' in dirs:
                    dirs.remove(b'proc')
                # SLICING WITH [:] SO THAT THE LIST ID STAYS THE SAME
                dirs[:] = self.remove_excluded_dirs(dirs, root, self.prep_excluded)

                self.crawl_signal.emit(
                    root.decode(encoding='utf-8', errors='ignore'))

                if self.lite:
                    for dname in dirs:
                        dir_list.append(('1', os.path.join(root, dname).decode(
                            encoding='UTF-8', errors='ignore')))
                    for fname in files:
                        file_list.append(('0', os.path.join(root, fname).decode(
                            encoding='UTF-8', errors='ignore')))
                else:
                    # MOON, 2023-12-31
                    # I don't need the folder, pdf is enough
                    # for dname in dirs:
                    #     path = os.path.join(root, dname)
                    #     utf_path = path.decode(encoding='utf-8', errors='ignore')
                    #     try:
                    #         stats = os.lstat(path)
                    #         epoch_time = int(stats.st_mtime.__trunc__())
                    #     except:
                    #         print("Can't access: " + str(path))
                    #         epoch_time = 0
                    #     dir_list.append(('1', utf_path, '', '', '', epoch_time))
                    # End
                    for fname in files:
                        papername = self.check_paper_name(fname)
                        if papername == False:
                            continue
                        
                        path = os.path.join(root, fname)
                        utf_path = path.decode(encoding='utf-8', errors='ignore')
                        try:
                            stats = os.lstat(path)
                            size = stats.st_size
                            epoch_time = int(stats.st_mtime.__trunc__())
                        except:
                            print("Can't access: " + str(path))
                            size = 0
                            epoch_time = 0
                        # Get the metadata from Table metadata
                        # Use the lower case of the original filename/papername
                        q = "SELECT level, venue, year, tags, reflections FROM metadata where name = ?;"
                        query_metadata = run_query_metadata(q, (papername.lower(), ))
                        query_metadata = query_metadata.fetchone()
                        if query_metadata == None:
                            file_list.append(('0', utf_path, '', '', '', '', '', size, epoch_time))
                        else:
                            query_metadata = list(query_metadata)
                            for t in range(len(query_metadata)):
                                if query_metadata[t] == None:
                                    query_metadata[t] = ''
                            file_list.append(('0', utf_path, query_metadata[0], query_metadata[1], query_metadata[2], query_metadata[3], query_metadata[4], size, epoch_time))
        self.table = dir_list + file_list
        self.crawl_time = self.time_difference(tstart)

    def new_database(self):
        global con
        temp_db_path = TEMP_PATH + '/angry_database.db'
        tstart = datetime.now()

        if os.path.exists(temp_db_path):
            if con:
                con.close()
            os.remove(temp_db_path)

        con = sqlite3.connect(temp_db_path, check_same_thread=False)
        cur = con.cursor()

        if self.lite:
            if self.fts5_pragma_check():
                cur.execute('''CREATE VIRTUAL TABLE angry_table
                                USING fts5(directory UNINDEXED, path)''')
                cur.execute('''PRAGMA user_version = 4;''')
            else:
                cur.execute('''CREATE VIRTUAL TABLE angry_table
                                USING fts4(directory, path,
                                           notindexed=directory)''')
                cur.execute('''PRAGMA user_version = 3;''')

            cur.executemany('''INSERT INTO angry_table VALUES (?, ?)''',
                            self.table)

        else:
            if self.fts5_pragma_check():
                # MOON, 2023-12-31
                # is_dir, path, proficiency, venue, tags, reflection, size, date
                cur.execute('''CREATE VIRTUAL TABLE angry_table
                                USING fts5(directory UNINDEXED,
                                           path,
                                           level,
                                           venue,
                                           year,
                                           tags,
                                           reflections,
                                           size UNINDEXED, 
                                           date UNINDEXED)''')
                cur.execute('''PRAGMA user_version = 4;''')
            else:
                cur.execute('''CREATE VIRTUAL TABLE angry_table
                                USING fts4(directory, path, size, date,
                                           notindexed=directory,
                                           notindexed=size,
                                           notindexed=date)''')
                cur.execute('''PRAGMA user_version = 3;''')

            cur.executemany('''INSERT INTO angry_table VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            self.table)

        con.commit()
        self.database_time = self.time_difference(tstart)

    def replace_old_db_with_new(self):
        global con
        global DATABASE_PATH

        temp_db_path = TEMP_PATH + '/angry_database.db'

        dir_path = os.path.dirname(DATABASE_PATH)

        if not os.path.exists(temp_db_path):
            return
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        if con:
            con.close()
        shutil.move(temp_db_path, DATABASE_PATH)

        con = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        con.create_function("regexp", 2, regexp)

    def time_difference(self, tstart):
        time_diff = datetime.now() - tstart
        mins, secs = divmod(time_diff.seconds, 60)
        return '{:0>2d}:{:0>2d}'.format(mins, secs)

    def remove_excluded_dirs(self, dirs, root, to_ignore):
        after_exclusion = []

        for x in dirs:
            for z in to_ignore:
                if x == z['ign']:
                    if z['case'] == 1:
                        if root == z['up']:
                            self.show_ignored(root, z['ign'])
                            break
                    elif z['case'] == 2:
                        self.show_ignored(root, z['ign'])
                        break
                    elif z['case'] == 3:
                        y = [k for k in root.split(b'/') if k]
                        if y[-1] == z['up']:
                            self.show_ignored(root, z['ign'])
                            break
            else:
                after_exclusion.append(x)
        return after_exclusion

    def show_ignored(self, root, item):
        r = root.decode(encoding='utf-8', errors='ignore')
        i = item.decode(encoding='utf-8', errors='ignore')
        if r == '/':
            print('Ignoring directory: /{}'.format(i))
        else:
            print('Ignoring directory: {}/{}'.format(r, i))

    # FTS5 IS A NEW EXTENSION OF SQLITE
    # SQLITE NEEDS TO BE COMPILED WITH FTS5 ENABLED
    def fts5_pragma_check(self):
        with sqlite3.connect(':memory:') as conn:
            cur = conn.cursor()
            cur.execute('pragma compile_options;')
            available_pragmas = cur.fetchall()

        return ('ENABLE_FTS5', ) in available_pragmas


# THREAD FOR GETTING MIMETYPE OF A FILE CURRENTLY SELECTED
class ThreadMimetype(Qc.QThread):
    mime_signal = Qc.pyqtSignal(str, str)

    def __init__(self, path, parent=None):
        super().__init__()
        self.path = path

    def run(self):
        if not os.path.exists(self.path):
            mimetype = 'NOT FOUND'
        else:
            mime = subprocess.Popen(['xdg-mime',
                                     'query',
                                     'filetype',
                                     self.path],
                                    stdout=subprocess.PIPE)
            mime.wait()
            if mime.returncode == 0:
                mimetype = str(mime.communicate()[0].decode('latin-1').strip())
            elif mime.returncode == 5:
                mimetype = 'NO PERMISSION'
            else:
                mimetype = 'NOPE'

        self.mime_signal.emit(self.path, mimetype)

def split_sentence(sentence, max_chars_per_line=100):
    lines = sentence.split("\n")
    result_lines = []

    for line in lines:
        words = line.split()
        current_line = ""

        for word in words:
            if len(current_line) + len(word) + 1 <= max_chars_per_line:  # Add 1 for the space between words
                current_line += word + " "
            else:
                result_lines.append(current_line.strip())
                current_line = word + " "

        # Add the remaining words to the last line
        if current_line:
            result_lines.append(current_line.strip())

    return "\n".join(result_lines)

class AngryTableModel(Qg.QStandardItemModel):
    r'''
    MOON, 2024-01-08
    Replace `Qc.QAbstractTableModel` with `Qg.QStandardItemModel`, and remove the original methods `data()` and `sort()`.
    This helps me to use ToolTip (I don't know why the original code in ANGRYsearch can not work well with ToolTip).

    https://doc.qt.io/qtforpython-5/PySide2/QtGui/QStandardItemModel.html
    '''
    pass


# CUSTOM TABLE VIEW TO EASILY ADJUST ROW HEIGHT AND COLUMN WIDTH
class AngryTableView(Qw.QTableView):
    def __init__(self, lite=True, row_height=0, parent=None):
        super().__init__()
        self.lite = lite
        if row_height and row_height != 0:
            self.verticalHeader().setDefaultSectionSize(row_height)

    def resizeEvent(self, event):
        width = event.size().width()
        if self.lite:
            self.setColumnWidth(0, int(width * 0.40))
            self.setColumnWidth(1, int(width * 0.60))
        else:
            # MOON, You can modify the column width
            width_col = [0.38, 0.03, 0.04, 0.03, 0.18, 0.22, 0.05, 0.07]
            for i in range(7):
                self.setColumnWidth(i, int(width * width_col[i]))

    # ROW IS HIGHLIGHTED THE MOMENT THE TABLE IS FOCUSED
    def focusInEvent(self, event):
        Qw.QTableView.focusInEvent(self, event)
        row = self.currentIndex().row()
        if row != -1:
            self.selectRow(row)

    def keyPressEvent(self, event):
        # ENTER KEY AND NUMPAD ENTER, AND WITH SHIFT
        if event.key() == 16777220 or event.key() == 16777221:
            index = self.currentIndex()
            if event.modifiers() == Qc.Qt.ShiftModifier:
                self.parent().parent().key_press_Enter(index, shift=True)
                return
            self.parent().parent().key_press_Enter(index, shift=False)
            return

        # TAB KEY GOES TO NEXT WIDGET NOT NEXT ROW IN THE TABLE
        if event.key() == 16777217:
            self.clearSelection()
            self.parent().focusNextChild()
            return

        # SHIFT + TAB KEY
        if event.key() == 16777218:
            self.clearSelection()
            self.parent().focusPreviousChild()
            return

        Qw.QTableView.keyPressEvent(self, event)

    def contextMenuEvent(self, event):
        right_click_menu = Qw.QMenu(self)

        act_open = right_click_menu.addAction('Open')
        act_open.triggered.connect(self.parent().parent().right_clk_open)

        act_open_evince = right_click_menu.addAction('Open With Evince')
        act_open_evince.triggered.connect(self.parent().parent().right_clk_open_evince)

        act_open_path = right_click_menu.addAction('Open Path')
        act_open_path.triggered.connect(self.parent().parent().right_clk_path)

        right_click_menu.addSeparator()

        # MOON, 2023-12-31
        # I don't know why the currentIndex().column() inside right_clk_modify() always returns 0
        # Thus, I use row and col to save the value of row and col, then use lambda to transfer the argument
        row = self.currentIndex().row()
        col = self.currentIndex().column()
        act_copy = right_click_menu.addAction('Copy')
        act_copy.triggered.connect(lambda: self.parent().parent().right_clk_copy(row, col))

        act_copy_path = right_click_menu.addAction('Copy Path')
        act_copy_path.triggered.connect(self.parent().parent().right_clk_copy_path)

        act_modify = right_click_menu.addAction('Modify')
        act_modify.triggered.connect(lambda: self.parent().parent().right_clk_modify(row, col))

        right_click_menu.exec_(event.globalPos())


# THE PRIMARY GUI DEFINING INTERFACE WIDGET, THE WIDGET WITHIN THE MAINWINDOW
class CenterWidget(Qw.QWidget):
    def __init__(self, setting_params=None):
        super().__init__()
        self.setting_params = setting_params
        self.search_input = Qw.QLineEdit()
        
        # MOON, 2023-12-31
        self.combobox = Qw.QComboBox()
        self.combobox.addItem("    Path     ")
        self.combobox.addItem("    Venue    ")
        self.combobox.addItem("    Year     ")
        self.combobox.addItem("    Tags     ")

        self.table = AngryTableView(self.setting_params['angrysearch_lite'],
                                    self.setting_params['row_height'])
        self.upd_button = Qw.QPushButton('    Update    ')
        self.fts_checkbox = Qw.QCheckBox()

        grid = Qw.QGridLayout()
        grid.setSpacing(10)
        
        grid.addWidget(self.search_input, 0, 0)
        grid.addWidget(self.fts_checkbox, 0, 1)
        grid.addWidget(self.upd_button, 0, 2)
        grid.addWidget(self.combobox, 0, 3)
        
        grid.addWidget(self.table, 1, 0, 1, 4)
        self.setLayout(grid)

        self.setTabOrder(self.search_input, self.table)
        self.setTabOrder(self.table, self.upd_button)


# THE MAIN APPLICATION WINDOW WITH THE STATUS BAR AND LOGIC
# LOADS AND SAVES QSETTINGS FROM ~/.config/angrysearch
# INITIALIZES AND SETS GUI, WAITING FOR USER INPUTS
class AngryMainWindow(Qw.QMainWindow):
    def __init__(self, parent=None):
        super().__init__()
        self.settings = Qc.QSettings(CONFIG_PATH, Qc.QSettings.IniFormat)
        self.setting_params = {
            'angrysearch_lite': False,
            'fts': True,
            'typing_delay': False,
            'darktheme': False,
            'fm_path_doubleclick_selects': False,
            'icon_theme': 'adwaita',
            'file_manager': 'xdg-open',
            'row_height': 0,
            'number_of_results': 500,
            'directories_excluded': [],
            'conditional_mounts_for_autoupdate': [],
            'notifications': True,
            'regex_mode': False,
            'close_on_execute': False
        }

        # FOR REGEX MODE, WHEN REGEX QUERY CAN BE RUN SO ONLY ONE ACCESS DB
        self.regex_query_ready = True

        self.read_settings()
        self.init_gui()

    def keyPressEvent(self, event):
        if type(event) == Qg.QKeyEvent:
            # ESC
            if event.key() == 16777216:
                self.close()
            # CTRL + Q
            if event.key() == 81:
                if event.modifiers() == Qc.Qt.ControlModifier:
                    self.close()
            # F6 KEY
            if event.key() == 16777269:
                self.center.search_input.selectAll()
                self.center.search_input.setFocus()
            # ALT + D
            if event.key() == 68 and event.modifiers() == Qc.Qt.AltModifier:
                self.center.search_input.selectAll()
                self.center.search_input.setFocus()
            # CTRL + L
            if event.key() == 76:
                if event.modifiers() == Qc.Qt.ControlModifier:
                    self.center.search_input.selectAll()
                    self.center.search_input.setFocus()
            # F8 FOR REGEX SEARCH MODE
            if event.key() == 16777271:
                self.setting_params['regex_mode'] = not self.setting_params['regex_mode']
                self.settings.setValue('regex_mode', self.setting_params['regex_mode'])
                self.regex_mode_color_indicator()
                if self.setting_params['regex_mode']:
                    self.status_bar.showMessage('REGEX MODE ENABLED')
                else:
                    self.status_bar.showMessage('REGEX MODE DISABLED')
            # CTRL + W
            if event.key() == 87:
                if event.modifiers() == Qc.Qt.ControlModifier:
                    input_text = self.center.search_input.text().split()
                    if not input_text:
                        return
                    last_removed = ' '.join(input_text[:-1])
                    if len(input_text) > 1:
                        last_removed = last_removed + ' '
                    self.center.search_input.setText(last_removed)

            event.accept()
        else:
            event.ignore()

    def regex_mode_color_indicator(self):
        if self.setting_params['regex_mode']:
            self.center.search_input.setStyleSheet(
                'background: #FF6A00; color: #000000;')
        else:
            self.center.search_input.setStyleSheet('')

    def read_settings(self):
        # MOON, 2024-01-01
        # It saves the last run geometry, so `resize` below has no effect
        if self.settings.value('Last_Run/geometry'):
            self.restoreGeometry(self.settings.value('Last_Run/geometry'))
        else:
            # MOON, 2023-12-30
            self.resize(2100, 800)
            # End

            qr = self.frameGeometry()
            cp = Qw.QDesktopWidget().availableGeometry().center()
            qr.moveCenter(cp)
            self.move(qr.topLeft())

        if self.settings.value('Last_Run/window_state'):
            self.restoreState(self.settings.value('Last_Run/window_state'))

        self.read_qsettings_item('angrysearch_lite', 'bool')
        self.read_qsettings_item('fast_search_but_no_substring', 'bool')
        self.read_qsettings_item('typing_delay', 'bool')
        self.read_qsettings_item('darktheme', 'bool')
        self.read_qsettings_item('fm_path_doubleclick_selects', 'bool')
        self.read_qsettings_item('icon_theme', 'str')
        self.read_qsettings_item('row_height', 'int')
        self.read_qsettings_item('number_of_results', 'int')
        self.read_qsettings_item('directories_excluded', 'list')
        self.read_qsettings_item('file_manager', 'fm')
        self.read_qsettings_item('conditional_mounts_for_autoupdate', 'list')
        self.read_qsettings_item('notifications', 'bool')
        self.read_qsettings_item('regex_mode', 'bool')
        self.read_qsettings_item('close_on_execute', 'bool')

        if self.settings.value('Last_Run/last_sort'):
            k = self.settings.value('Last_Run/last_sort')
            if isinstance(k, list) and len(k) == 2:
                if self.setting_params['angrysearch_lite'] and int(k[0]) > 1:
                    k[0] = 1
                self.setting_params['last_sort'] = [int(x) for x in k]
            else:
                self.setting_params['last_sort'] = [1, 0]
        else:
            self.setting_params['last_sort'] = [1, 0]

    def read_qsettings_item(self, item, type_):
        if self.settings.value(item):
            k = self.settings.value(item)
            if type_ == 'bool':
                if k.lower() in ['false', 'no', '0', 'n', 'none']:
                    if item == 'fast_search_but_no_substring':
                        item = 'fts'
                    self.setting_params[item] = False
                else:
                    self.setting_params[item] = True
            if type_ == 'str':
                self.setting_params[item] = k
            if type_ == 'int':
                if k.isdigit():
                    self.setting_params[item] = int(k)
            if type_ == 'list':
                self.setting_params[item] = shlex.split(k.strip())
            if type_ == 'fm':
                if k in ['', 'xdg-open']:
                    self.setting_params[item] = self.detect_file_manager()
                else:
                    self.setting_params[item] = k
        else:
            if type_ == 'fm':
                self.setting_params[item] = self.detect_file_manager()

    def detect_file_manager(self):
        try:
            fm = subprocess.check_output(['xdg-mime',
                                          'query',
                                          'default',
                                          'inode/directory'])
            detected_fm = fm.decode('utf-8').strip().lower()
            known_fm = ['dolphin',
                        'nemo',
                        'nautilus',
                        'doublecmd',
                        'thunar',
                        'pcmanfm-qt',
                        'pcmanfm',
                        'spacefm']
            for x in known_fm:
                if x in detected_fm:
                    print('autodetected file manager: ' + x)
                    return x
            return 'xdg-open'

        except Exception as err:
            print(err)
            return 'xdg-open'

    def closeEvent(self, event):
        self.settings.setValue('Last_Run/geometry', self.saveGeometry())
        self.settings.setValue('Last_Run/window_state', self.saveState())
        if not self.settings.contains('angrysearch_lite'):
            self.settings.setValue('angrysearch_lite', True)
        if not self.settings.contains('fast_search_but_no_substring'):
            self.settings.setValue('fast_search_but_no_substring', True)
        if not self.settings.contains('typing_delay'):
            self.settings.setValue('typing_delay', False)
        if not self.settings.contains('darktheme'):
            self.settings.setValue('darktheme', False)
        if not self.settings.contains('fm_path_doubleclick_selects'):
            self.settings.setValue('fm_path_doubleclick_selects', False)
        if not self.settings.contains('icon_theme'):
            self.settings.setValue('icon_theme', 'adwaita')
        if not self.settings.contains('file_manager'):
            self.settings.setValue('file_manager', '')
        if not self.settings.contains('row_height'):
            self.settings.setValue('row_height', 0)
        if not self.settings.contains('number_of_results'):
            self.settings.setValue('number_of_results', 500)
        if not self.settings.contains('directories_excluded'):
            self.settings.setValue('directories_excluded', '')
        if not self.settings.contains('conditional_mounts_for_autoupdate'):
            self.settings.setValue('conditional_mounts_for_autoupdate', '')
        if not self.settings.contains('notifications'):
            self.settings.setValue('notifications', True)
        if not self.settings.contains('regex_mode'):
            self.settings.setValue('regex_mode', False)
        if not self.settings.contains('close_on_execute'):
            self.settings.setValue('close_on_execute', False)

        # TRAY ICON NEEDS TO BE HIDDEN
        # SO THAT THE MAIN WINDOW INSTANCE AUTOMATICALLY DELETES IT ON CLOSING
        #self.tray_icon.hide()
        event.accept()

    def init_gui(self):
        self.icon = self.get_tray_icon()
        self.setWindowIcon(self.icon)

        if self.setting_params['darktheme']:
            self.style_data = ''
            if os.path.isfile('qdarkstylesheet.qss'):
                f = open('qdarkstylesheet.qss', 'r')
                self.style_data = f.read()
                f.close()
                self.setStyleSheet(self.style_data)
            elif os.path.isfile('/usr/share/angrysearch/qdarkstylesheet.qss'):
                f = open('/usr/share/angrysearch/qdarkstylesheet.qss', 'r')
                self.style_data = f.read()
                f.close()
                self.setStyleSheet(self.style_data)
            elif os.path.isfile('/opt/angrysearch/qdarkstylesheet.qss'):
                f = open('/opt/angrysearch/qdarkstylesheet.qss', 'r')
                self.style_data = f.read()
                f.close()
                self.setStyleSheet(self.style_data)

        self.queries_threads = []
        self.waiting_threads = []
        self.mime_type_threads = []
        self.last_keyboard_input = {'time': 0, 'input': ''}
        self.last_number_of_results = 500
        self.file_list = []
        self.icon_dictionary = self.get_mime_icons()

        self.center = CenterWidget(self.setting_params)
        self.setCentralWidget(self.center)

        self.setWindowTitle('ANGRYsearch')
        self.status_bar = Qw.QStatusBar(self)
        self.setStatusBar(self.status_bar)

        self.center.fts_checkbox.setToolTip(
            'check = fast search but no substrings\n'
            'uncheck = slower but substrings work')

        if self.setting_params['fts']:
            self.center.fts_checkbox.setChecked(True)
        self.center.fts_checkbox.stateChanged.connect(self.checkbox_fts_click)

        self.center.table.setGridStyle(0)
        self.center.table.setSortingEnabled(True)
        self.center.table.sortByColumn(1, 0)
        self.center.table.setEditTriggers(Qw.QAbstractItemView.NoEditTriggers)
        self.center.table.setSelectionBehavior(Qw.QAbstractItemView.SelectRows)
        self.center.table.horizontalHeader().setStretchLastSection(True)
        self.center.table.setAlternatingRowColors(True)
        self.center.table.verticalHeader().setVisible(False)
        self.center.table.setVerticalScrollBarPolicy(Qc.Qt.ScrollBarAlwaysOn)
        self.center.table.setSelectionMode(
            Qw.QAbstractItemView.SingleSelection)

        self.center.table.setItemDelegate(self.HTMLDelegate())

        self.center.table.activated.connect(self.double_click_enter)

        self.center.search_input.textChanged[str].connect(
            self.wait_for_finishing_typing)
        self.center.upd_button.clicked.connect(self.clicked_button_updatedb)

        self.database_age()

        self.show()
        self.show_first_500()
        #self.make_sys_tray()

        self.center.search_input.setFocus()
        self.center.search_input.returnPressed.connect(self.focusNextChild)

        self.regex_mode_color_indicator()

    # MOON, 2024-01-02, I donot need the icon appearing in the top of the screen
    # so I comment this function.
    def make_sys_tray(self):
        if Qw.QSystemTrayIcon.isSystemTrayAvailable():
            menu = Qw.QMenu()
            menu.addAction('v1.0.4')
            menu.addSeparator()
            exitAction = menu.addAction('Quit')
            exitAction.triggered.connect(self.close)

            self.tray_icon = Qw.QSystemTrayIcon()
            self.tray_icon.setIcon(self.icon)
            self.tray_icon.setContextMenu(menu)
            self.tray_icon.show()
            self.tray_icon.setToolTip('ANGRYsearch')
            self.tray_icon.activated.connect(self.sys_tray_clicking)

    def sys_tray_clicking(self, reason):
        if (reason == Qw.QSystemTrayIcon.DoubleClick or
                reason == Qw.QSystemTrayIcon.Trigger):
            self.show()
        elif (reason == Qw.QSystemTrayIcon.MiddleClick):
            self.close()

    def get_tray_icon(self):
        base64_data = '''iVBORw0KGgoAAAANSUhEUgAAABYAAAAWCAYAAADEtGw7AAAABHN
                         CSVQICAgIfAhkiAAAAQNJREFUOI3t1M9KAlEcxfHPmP0xU6Ogo
                         G0teoCiHjAIfIOIepvKRUE9R0G0KNApfy0c8hqKKUMrD9zVGc4
                         9nPtlsgp5n6qSVSk7cBG8CJ6sEX63UEcXz4jE20YNPbygPy25Q
                         o6oE+fEPXFF7A5yA9Eg2sQDcU3sJd6k89O4iiMcYKVol3rH2Mc
                         a1meZ4hMdNPCIj+SjHHfFZU94/0Nwlv4rWoY7vhrdeLNoO86bG
                         lym/ge3lsHDdI2fojbBG6sUtzOiQ1wQOwk6GwWKHeJyHtxOcFi
                         0TpFaxmnhNcyIW45bQ6RS3Hq4MeB7Ltyahki9Gd2xidWiwG9va
                         nCZqi7xlZGVHfwN6+5nU/ccBUYAAAAASUVORK5CYII='''

        pm = Qg.QPixmap()
        pm.loadFromData(base64.b64decode(base64_data))
        i = Qg.QIcon()
        i.addPixmap(pm)
        return i

    # OFF BY DEFAULT
    # 0.2 SEC DELAY TO LET USER FINISH TYPING BEFORE INPUT BECOMES A DB QUERY
    def wait_for_finishing_typing(self, input_text):
        if not self.setting_params['typing_delay']:
            self.new_query_new_thread(input_text)
            return
        self.last_keyboard_input = input_text
        self.waiting_threads.append(ThreadDelayDBQuery(input_text))
        self.waiting_threads[-1].delay_signal.connect(
            self.waiting_done, Qc.Qt.QueuedConnection)
        self.waiting_threads[-1].start()

    def waiting_done(self, waiting_data):
        if self.last_keyboard_input == waiting_data:
            self.new_query_new_thread(waiting_data)
            if len(self.waiting_threads) > 100:
                del self.waiting_threads[0:80]

    # NEW DATABASE QUERY ADDED TO LIST OF RECENT RUNNING THREADS
    def new_query_new_thread(self, input_text):
        if not self.setting_params['fts'] or self.setting_params['regex_mode']:
            self.status_bar.showMessage(' ...')

        if input_text == '' and self.regex_query_ready:
            self.show_first_500()
            return

        if self.setting_params['regex_mode']:
            try:
                re.compile(input_text)
                is_valid = True
            except re.error:
                is_valid = False

            if not is_valid:
                self.status_bar.showMessage('regex not valid')
                return

            self.queries_threads.append(
                {'input': input_text,
                 'thread': ThreadDBQuery(input_text, self.setting_params)})

            self.queries_threads[-1]['thread'].db_query_signal.connect(
                self.database_query_done, Qc.Qt.QueuedConnection)
            if self.regex_query_ready:
                self.queries_threads[-1]['thread'].start()
                self.regex_query_ready = False
        else:
            # MOON, 2024-01-08, search by the current text
            attribute = self.center.combobox.currentText()        
            attribute = attribute.replace(" ", "").lower()
            self.queries_threads.append(
                {'input': input_text,
                 'thread': ThreadDBQuery(input_text, attribute, self.setting_params)})

            self.queries_threads[-1]['thread'].db_query_signal.connect(
                self.database_query_done, Qc.Qt.QueuedConnection)
            self.queries_threads[-1]['thread'].start()

        if len(self.queries_threads) > 100:
            del self.queries_threads[0:80]

    # CHECK IF THE RESULTS COME FROM THE LAST ONE OR THERE ARE SOME STILL GOING
    def database_query_done(self, db_query, db_query_result, words_quoted):
        self.regex_query_ready = True
        if self.setting_params['regex_mode']:
            if db_query != self.queries_threads[-1]['input']:
                self.new_query_new_thread(self.queries_threads[-1]['input'])

        if db_query == self.queries_threads[-1]['input']:
            # MOON, 2023-12-31
            self.process_q_resuls(db_query, db_query_result, words_quoted)

    # FORMAT DATA FOR THE MODEL
    # Prosess the query results
    def process_q_resuls(self, db_query, db_query_result, words_quoted=None):
        if words_quoted is None:
            words_quoted = []
        model_data = []

        if self.setting_params['regex_mode']:
            rx = '({})'.format(db_query)
        else:
            # INSTEAD OF re.escape() PROBLEMATIC CHARACTERS ARE REMOVED
            for x in ['\"', '\'', '\\', '?', '+', '[', ']', '(', ')', '*']:
                db_query = db_query.replace(x, '')

            strip_and_split = db_query.strip().split()
            preparation_list = []

            for x in strip_and_split:
                if x in words_quoted:
                    z = '(?<![0-9a-zA-Z]){}(?![0-9a-zA-Z])'.format(x)
                    preparation_list.append(z)
                else:
                    preparation_list.append(x)
            joined_by_pipe = '|'.join(preparation_list)
            rx = '({})'.format(joined_by_pipe)

        self.regex_queries = re.compile(rx, re.IGNORECASE)

        for tup in db_query_result:
            keys = ['is_dir', 'path', 'level', 'venue', 'year', 'tags', 'reflections', 'size', 'date']
            item = {}
            for i in range(len(tup)):
                item[keys[i]] = tup[i]

            split_by_slash = item['path'].split('/')

            name = _name = split_by_slash[-1]
            path = _path = '/'.join(split_by_slash[:-1]) or '/'
            tags = item['tags']

            if db_query != '':
                name = self.bold_text(name)
                path = self.bold_text(path)
                tags = self.bold_text(tags)

            # NAME ITEM IN THE FIRST COLUMN
            # MOON, 2023-01-01, I remveo the `.pdf`
            name = Qg.QStandardItem(name[:-4])
            name._name = _name.lower()
            name._exact_name = _name
            name._parent_dir = _path
            name._fullpath = item['path']
            name._is_dir = item['is_dir']

            if item['is_dir'] == '1':
                name.setIcon(self.icon_dictionary['folder'])
            else:
                short_mime = mimetypes.guess_type(_name)[0]
                if short_mime:
                    archives = ['x-tar',
                                'zip',
                                'x-rar-compressed',
                                'x-7z-compressed']
                    short_mime = short_mime.split('/')
                    if short_mime[0] in self.icon_dictionary:
                        name.setIcon(self.icon_dictionary[short_mime[0]])
                    elif short_mime[1] in self.icon_dictionary:
                        name.setIcon(self.icon_dictionary[short_mime[1]])
                    elif short_mime[1] in archives:
                        name.setIcon(self.icon_dictionary['archive'])
                    else:
                        name.setIcon(self.icon_dictionary['file'])
                else:
                    name.setIcon(self.icon_dictionary['file'])

            # MOON, 2023-12-30
            level = Qg.QStandardItem(item['level'])

            #venue = Qg.QStandardItem('<kbd style="background-color: lightgrey">{}</kbd>'.format(item['venue']))
            venue = Qg.QStandardItem(item['venue'])
            year = Qg.QStandardItem(item['year'])

            tags = Qg.QStandardItem(tags)
            tags._tags = item['tags']
            #tags.setBackground(Qg.QColor('#348ceb'))
            tags.setToolTip(tags._tags)

            # Change the fonts
            # https://blog.csdn.net/gixome/article/details/120782015
            Qw.QToolTip.setFont(Qg.QFont('Times New Roman', 15)) # Times New Roman, Consolas
            tooltip_palette = Qg.QPalette()
            # Change the style
            # https://stackoverflow.com/questions/34197295/how-to-change-the-background-color-of-qtooltip-of-a-qtablewidget-item
            tooltip_palette.setColor(Qg.QPalette.ToolTipBase, Qg.QColor("white")) # "#F6F6F6"
            tooltip_palette.setColor(Qg.QPalette.ToolTipText, Qg.QColor("black")) # #706F6F"
            Qw.QToolTip.setPalette(tooltip_palette)

            reflections = Qg.QStandardItem(item['reflections'])
            reflections.setToolTip(split_sentence(item['reflections']))

            file_size = ''
            bytesize = 0
            if item['size'] != '':
                bytesize = int(item['size'])
                file_size = self.readable_filesize(bytesize)
            file_size = Qg.QStandardItem(file_size)
            file_size._bytes = bytesize

            date = str(datetime.fromtimestamp(item['date']))[:-3] # I remove the second area
            date = Qg.QStandardItem(date)

            item = [name, level, venue, year, tags, reflections, file_size, date]
            model_data.append(item)
            
            # Sort `model_data` according to `date`.
            model_data = sorted(model_data, key=lambda x: x[-1], reverse=True)

        # MOON, 2024-01-08
        # construct AngryTableModel
        # https://blog.csdn.net/A642960662/article/details/123093350
        headers = ['Name', 'Level', 'Venue', 'Year', 'Tags', 'Reflections', 'Size', 'Date Modified']
        self.model = AngryTableModel(len(model_data), len(headers))
        self.model.setHorizontalHeaderLabels(headers)
        for i in range(self.model.rowCount()):
            for j in range(self.model.columnCount()):
                self.model.setItem(i, j, model_data[i][j])
        self.center.table.setModel(self.model)
        # End

        total = locale.format_string('%d', len(db_query_result), grouping=True)
        self.last_number_of_results = total
        self.status_bar.showMessage(total)

    def sorting_changed_received_signal(self, column, order):
        self.setting_params['last_sort'] = [column, order]
        self.settings.setValue('Last_Run/last_sort', [column, order])

    def bold_text(self, line):
        return re.sub(self.regex_queries, '<b>\\1</b>', line)
        #return re.sub(self.regex_queries, '<font color=blue>\\1</font>', line)

    # CREATES DICTIONARY WITH 6 MIME TYPES ICONS DEPENDING ON THEME
    def get_mime_icons(self):
        file_icon = self.style().standardIcon(Qw.QStyle.SP_FileIcon)
        icon_dic = {'folder': self.style().standardIcon(Qw.QStyle.SP_DirIcon),
                    'file': file_icon,
                    'image': file_icon,
                    'audio': file_icon,
                    'video': file_icon,
                    'text': file_icon,
                    'pdf': file_icon,
                    'archive': file_icon}

        # QT RESOURCE FILE WITH MIME ICONS AND DARK GUI THEME ICONS
        # IF NOT AVAILABLE ONLY 2 ICONS REPRESENTING FILE & DIRECTORY ARE USED
        try:
            import resource_file
            for key in icon_dic:
                icon = ':/mimeicons/{}/{}.png'.format(
                    self.setting_params['icon_theme'],
                    key)
                icon_dic[key] = Qg.QIcon(icon)
        except ImportError:
            pass

        return icon_dic

    def readable_filesize(self, nbytes):
        suffixes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        if nbytes == 0:
            return '0 B'
        i = 0
        while nbytes >= 1024 and i < len(suffixes) - 1:
            nbytes /= 1024.
            i += 1
        f = ('{:.2f}'.format(nbytes)).rstrip('0').rstrip('.')
        return '{} {}'.format(f, suffixes[i])

    # RUNS ON START OR ON EMPTY INPUT, SHOWS TOP OF THE FILESYSTEM
    # CHECKS THE DATABASE AGAINST SETTINGS AND IF ITS NOT EMPTY
    def show_first_500(self):
        global FTS5_AVAILABLE
        cur = con.cursor()

        cur.execute('''PRAGMA user_version;''')
        pragma_user_version = cur.fetchone()[0]
        if pragma_user_version == 4:
            FTS5_AVAILABLE = True
        if pragma_user_version < 3:
            self.tutorial()
            return

        cur.execute('''PRAGMA table_info(angry_table);''')
        d = len(cur.fetchall())

        if d == 0:
            self.tutorial()
            return

        if self.setting_params['angrysearch_lite'] and d == 4:
            self.tutorial()
            return

        if not self.setting_params['angrysearch_lite'] and d == 2:
            self.tutorial()
            return

        self.center.table.sortByColumn(self.setting_params['last_sort'][0],
                                       self.setting_params['last_sort'][1])

        self.center.table.setDisabled(False)
        cur.execute("SELECT * FROM angry_table LIMIT ?",
                    (self.setting_params['number_of_results'],))
        tuppled_500 = cur.fetchall()

        self.process_q_resuls('', tuppled_500)

        cur.execute("SELECT COALESCE(MAX(rowid), 0) FROM angry_table")
        total_rows_numb = cur.fetchone()[0]
        total = locale.format_string('%d', total_rows_numb, grouping=True)
        self.status_bar.showMessage(total)

    def key_press_Enter(self, QModelIndex, shift=False):
        if shift:
            self.double_click_enter(QModelIndex, True, True)
        else:
            self.double_click_enter(QModelIndex, True, False)

    def right_clk_open(self):
        qmodel_index = self.center.table.currentIndex()
        self.double_click_enter(qmodel_index, True, False)

    def right_clk_path(self):
        qmodel_index = self.center.table.currentIndex()
        self.double_click_enter(qmodel_index, True, True)

    def right_clk_open_evince(self):
        '''
        Since I find that evince is quite useful with the function of preview.
        I decide to add open with eevince. (2024-05-17)
        '''
        qmodel_index = self.center.table.currentIndex()
        column = qmodel_index.column()
        row = qmodel_index.row()
        item = self.model.itemFromIndex(self.model.index(row, 0))
        path = item._fullpath

        self.center.table.timeout = Qc.QTimer()
        self.center.table.timeout.setSingleShot(True)
        self.center.table.timeout.timeout.connect(self.row_color_back)

        if not os.path.exists(path):
            self.status_bar.showMessage('NOT FOUND')
            self.center.table.setStyleSheet('selection-background-color:red;')
            self.center.table.timeout.start(150)
            return
        else:
            self.center.table.setStyleSheet('selection-color:green;')
            self.center.table.timeout.start(150)

        subprocess.Popen(['evince', path])

        if self.setting_params['close_on_execute']:
            self.close()

    def right_clk_copy_path(self):
        qmodel_index = self.center.table.currentIndex()
        content = self.model.itemFromIndex(self.model.index(qmodel_index.row(), 0))._fullpath
        clipboard = Qw.QApplication.clipboard()
        clipboard.setText(content)

    def right_clk_copy(self, row, col):
        # I don't know why the currentIndex().column() here always returns 0
        # Thus, I use row and col to save the value of row and col, then use lambda to transfer the argument
        # qmodel_index = self.center.table.currentIndex()
        headertext = self.model.horizontalHeaderItem(col).text()
        if headertext == 'Name':
            content = self.model.itemFromIndex(self.model.index(row, col))._exact_name[:-4]
        elif headertext == 'Tags':
            content = self.model.itemFromIndex(self.model.index(row, col))._tags
        else:
            content = self.model.itemFromIndex(self.model.index(row, col)).text()
        clipboard = Qw.QApplication.clipboard()
        clipboard.setText(content)
    
    def right_clk_modify(self, row, col):
        # MOON, 2023-12-31
        # I don't know why the currentIndex().column() here always returns 0
        # Thus, I use row and col to save the value of row and col, then use lambda to transfer the argument
        # qmodel_index = self.center.table.currentIndex()
        headertext = self.model.horizontalHeaderItem(col).text()
        if headertext in ['Name', 'Size', 'Date Modified']:
            return
        else:
            qmodel = self.model.itemFromIndex(self.model.index(row, col))
            if self.model.horizontalHeaderItem(col).text() == 'Tags':
                placeholder = qmodel._tags
            else:
                placeholder = qmodel.text()
            if headertext == 'Reflections':
                # https://python.hotexamples.com/examples/PyQt5.QtWidgets/QInputDialog/resize/python-qinputdialog-resize-method-examples.html
                dlg = Qw.QInputDialog(self)
                dlg.setFont(Qg.QFont("Consolas", 12))
                # dlg.setInputMode(Qw.QInputDialog.TextInput)
                dlg.setOption(Qw.QInputDialog.InputDialogOption.UsePlainTextEditForTextInput)
                dlg_textedit = dlg.findChild(Qw.QPlainTextEdit)
                dlg_textedit.setLineWrapMode(Qw.QPlainTextEdit.WidgetWidth)

                dlg.setWindowTitle(headertext)
                dlg.setLabelText('- (motivation), + (contribution), ~ (reflection), > (cite), ? (issue), ...')
                dlg.setTextValue(placeholder)
                dlg.resize(1500, 900)
                ok = dlg.exec_()
                if ok:
                    text = dlg.textValue()
            else:
                text, ok = Qw.QInputDialog.getText(self, headertext, '{}'.format(placeholder), text=placeholder)
            if ok:
                # MOON, 2023-12-31
                # Update Text
                qmodel.setText(str(text))          
                seq = {"path": 0, 'level': 1, 'venue': 2, 'year': 3, 'tags': 4, 'reflections': 5}
                if headertext == "Tags":
                    qmodel.setToolTip(str(text))
                elif headertext == "Reflections":
                    qmodel.setToolTip(split_sentence(str(text)))
                path = self.model.itemFromIndex(self.model.index(row, seq['path']))._fullpath
                fname = self.model.itemFromIndex(self.model.index(row, seq['path']))._name[:-4]
                level = self.model.itemFromIndex(self.model.index(row, seq['level'])).text()
                venue = self.model.itemFromIndex(self.model.index(row, seq['venue'])).text()
                year = self.model.itemFromIndex(self.model.index(row, seq['year'])).text()
                if headertext == "Tags":
                    tags = str(text)
                else:
                    tags = self.model.itemFromIndex(self.model.index(row, seq['tags']))._tags
                reflections = self.model.itemFromIndex(self.model.index(row, seq['reflections'])).text()
                # Update some properties
                if headertext == "Tags":
                    qmodel._tags = str(text)
                # Update angry_table
                q = "UPDATE angry_table SET level = ?, venue = ?, year = ?, tags = ?, reflections = ? WHERE path = ?;"
                params = (level, venue, year, tags, reflections, path)
                run_update(q, params)
                # Update metadata
                q = "INSERT OR REPLACE INTO metadata (name, level, venue, year, tags, reflections) VALUES (?, ?, ?, ?, ?, ?);"
                params = (fname, level, venue, year, tags, reflections)
                run_update_metadata(q, params)

    # WHEN A ROW IS SELECTED IN TABLE VIEW, BY MOUSE OR KEYBOARD
    # MIMETYPE IS GET IN A THREAD TO KEEP THE INTERFACE RESPONSIVE
    def selection_happens(self, selected_item, deselected_item):
        if selected_item.indexes():
            row = selected_item.indexes()[0].row()
            path = self.model.itemFromIndex(row, 0)._fullpath

            self.mime_type_threads.append(
                {'path': path,
                 'thread': ThreadMimetype(path)})

            self.mime_type_threads[-1]['thread'].mime_signal.connect(
                self.mime_type_thread_done, Qc.Qt.QueuedConnection)
            self.mime_type_threads[-1]['thread'].start()
        else:
            self.status_bar.showMessage(self.last_number_of_results)
            return

    def mime_type_thread_done(self, path, selections_mimetype):
        if (path != self.mime_type_threads[-1]['path']):
            return
        self.status_bar.showMessage(selections_mimetype)

        if len(self.mime_type_threads) > 100:
            del self.mime_type_threads[0:80]

    # THE FIRST COLUMN DOUBLECLICK OPENS THE FILE IN ASSOCIATED PROGRAM
    # THE SECOND COLUMN OPENS THE LOCATION, ATTEMPTING HIGHLIGHTING FILE
    def double_click_enter(self, QModelIndex, from_enter=False, shift=False):
        column = QModelIndex.column()
        row = QModelIndex.row()
        # MOON, 2024-01-08
        item = self.model.itemFromIndex(self.model.index(row, 0))

        path = item._fullpath
        parent_dir = item._parent_dir
        last_item = item._name
        is_dir = (True if item._is_dir == '1' else False)

        if from_enter:
            column = 0
            if shift:
                column = 1

        self.center.table.timeout = Qc.QTimer()
        self.center.table.timeout.setSingleShot(True)
        self.center.table.timeout.timeout.connect(self.row_color_back)

        if not os.path.exists(path):
            self.status_bar.showMessage('NOT FOUND')
            # MOON 2024-01-08
            # https://stackoverflow.com/questions/58758447/how-to-fix-module-platform-has-no-attribute-linux-distribution-when-instal
            # Remove the following code
            # if platform.linux_distribution()[0].lower() == 'ubuntu':
            #     self.center.table.setStyleSheet('selection-color:red;')
            # else:
            self.center.table.setStyleSheet('selection-background-color:red;')
            self.center.table.timeout.start(150)
            return
        else:
            self.center.table.setStyleSheet('selection-color:green;')
            self.center.table.timeout.start(150)

        fm = self.setting_params['file_manager']
        if column == 0:
            if is_dir:
                if fm != 'xdg-open':
                    subprocess.Popen([fm, path])
                else:
                    subprocess.Popen(['xdg-open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        else:
            if is_dir:
                if 'dolphin' in fm:
                    cmd = ['dolphin', '--select', path]
                else:
                    cmd = [fm, parent_dir]
                subprocess.Popen(cmd)
            else:
                if 'dolphin' in fm:
                    cmd = ['dolphin', '--select', path]
                    subprocess.Popen(cmd)
                elif fm in ['nemo', 'nautilus', 'doublecmd']:
                    cmd = [fm, path]
                    subprocess.Popen(cmd)
                elif fm in ['thunar', 'pcmanfm', 'pcmanfm-qt', 'spacefm']:
                    self.fm_highlight(fm, parent_dir, last_item)
                else:
                    cmd = [fm, parent_dir]
                    subprocess.Popen(cmd)

        if self.setting_params['close_on_execute']:
            self.close()

    # FOR THUNAR AND PCMANFM SO THAT THEY SELECT THE FILE/FOLDER
    # NOT JUST OPEN ITS PARENT FOLDER
    def fm_highlight(self, fm, parent_dir, last_item):
        if not self.setting_params['fm_path_doubleclick_selects']:
            cmd = [fm, parent_dir]
            subprocess.Popen(cmd)
            return
        cmd = [fm, parent_dir]
        subprocess.Popen(cmd)
        time.sleep(0.5)
        cmd = ['xdotool', 'type', last_item]
        subprocess.Popen(cmd)
        time.sleep(0.5)
        cmd = ['xdotool', 'key', 'Escape']
        subprocess.Popen(cmd)

    # FOR SPACEFM
    def fm_highlight_spacefm(self, fm, parent_dir, last_item):
        if not self.setting_params['fm_path_doubleclick_selects']:
            cmd = [fm, parent_dir]
            subprocess.Popen(cmd)
            return
        cmd = [fm, parent_dir]
        subprocess.Popen(cmd)
        time.sleep(0.5)
        cmd = ['spacefm', '-s', 'set', 'selected_filenames', last_item]
        subprocess.Popen(cmd)

    def row_color_back(self):
        self.center.table.setStyleSheet('')

    # USE OR DO NOT USE FTS EXTENSION TABLES IN THE DATABASE
    # FAST SEARCH OR SEARCH WITH SUBSTRINGS
    def checkbox_fts_click(self, state):
        print('checkbox_fts_click')
        if state == Qc.Qt.Checked:
            self.setting_params['fts'] = True
            self.settings.setValue('fast_search_but_no_substring', True)
        else:
            self.setting_params['fts'] = False
            self.settings.setValue('fast_search_but_no_substring', False)
        current_search = self.center.search_input.text()
        self.new_query_new_thread(current_search)
        self.center.search_input.setFocus()

    # SHOWN WHEN THERES NO DATABASE OR LITE SETTINGS CHANGED
    def tutorial(self):
        self.center.search_input.setDisabled(True)
        conf_file = self.settings.fileName()
        chat = [
            '   • config file is in {}'.format(conf_file),
            '   • database is in {}/angrysearch/angry_database.db'.format(
                  CACHE_PATH),
            '   • one million files can take ~200MB and ~2 min to index',
            '',
            '   • double-click on name opens it in associated application',
            '   • double-click on path opens the location in file manager',
            '',
            '   • checkbox in the right top corner changes search behavior',
            '   • by default checked, it provides very fast searching',
            '   • drawback is that it can\'t do word bound substrings',
            '   • it would not find "Pi<b>rate</b>s", or Whip<b>lash</b>"',
            '   • it would find "<b>Pir</b>ates", or "The-<b>Fif</b>th"',
            '   • unchecking it provides substring searches, but slower',
        ]

        self.center.table.setModel(Qc.QStringListModel(chat))
        self.center.table.setDisabled(True)
        self.status_bar.showMessage(
            'Press the update button in the top right corner')

    # CREATE INSTANCE OF UPDATE THE DATABASE DIALOG WINDOW
    def clicked_button_updatedb(self):
        self.center.search_input.setDisabled(False)
        self.u = UpdateDialogWindow(self)
        self.u.window_close_signal.connect(
            self.update_window_close, Qc.Qt.QueuedConnection)
        self.u.icon_theme_signal.connect(
            self.theme_change_icon, Qc.Qt.QueuedConnection)
        self.u.exec_()
        self.center.search_input.setFocus()

    def update_window_close(self, text):
        if text == 'update_win_ok':
            self.center.search_input.setText('')
            self.show_first_500()
            self.database_age()

    def theme_change_icon(self, text):
        self.setting_params['icon_theme'] = text
        self.settings.setValue('icon_theme', text)
        self.icon_dictionary = self.get_mime_icons()
        self.new_query_new_thread(self.center.search_input.text())

    # SHOW AGE OF DATABASE IN TOOLTIP OF THE UPDATE BUTTON
    def database_age(self):
        global DATABASE_PATH

        def readable_time():
            if os.path.exists(DATABASE_PATH):
                seconds = int(time.time() - os.path.getmtime(DATABASE_PATH))

                if seconds < 3600:
                    rounded = round(seconds / 60)
                    if rounded == 1:
                        return '1 minute old'
                    return '{} minutes old'.format(rounded)

                if seconds < 172800:
                    rounded = round(seconds / 3600)
                    if rounded == 1:
                        return '1 hour old'
                    return '{} hours old'.format(rounded)
                else:
                    rounded = round(seconds / 86400)
                    if rounded == 1:
                        return '1 day old'
                    return '{} days old'.format(rounded)
            else:
                return 'No Database Age'

        self.center.upd_button.setToolTip(readable_time())

    # CUSTOM DELEGATE TO GET HTML RICH TEXT IN LISTVIEW
    # ALLOWS USE OF <b></b> TAGS TO HIGHLIGHT SEARCHED PHRASE IN RESULTS
    class HTMLDelegate(Qw.QStyledItemDelegate):
        def __init__(self, parent=None):
            super().__init__()
            self.doc = Qg.QTextDocument(self)

        def paint(self, painter, option, index):
            painter.save()

            options = Qw.QStyleOptionViewItem(option)

            self.initStyleOption(options, index)
            self.doc.setHtml(options.text)
            options.text = ''

            style = (Qw.QApplication.style() if options.widget is None
                else options.widget.style())
            style.drawControl(Qw.QStyle.CE_ItemViewItem, options, painter)

            ctx = Qg.QAbstractTextDocumentLayout.PaintContext()

            if option.state & Qw.QStyle.State_Selected:
                ctx.palette.setColor(Qg.QPalette.Text,
                                     option.palette.color(
                                         Qg.QPalette.Active,
                                         Qg.QPalette.HighlightedText))
            else:
                ctx.palette.setColor(Qg.QPalette.Text,
                                     option.palette.color(
                                         Qg.QPalette.Active, Qg.QPalette.Text))

            textRect = style.subElementRect(Qw.QStyle.SE_ItemViewItemText,
                                            options, None)

            if index.column() != 0:
                textRect.adjust(5, 0, 0, 0)

            thefuckyourshitup_constant = 4
            margin = (option.rect.height() - options.fontMetrics.height()) // 2
            margin = margin - thefuckyourshitup_constant
            textRect.setTop(textRect.top() + margin)

            painter.translate(textRect.topLeft())
            painter.setClipRect(textRect.translated(-textRect.topLeft()))
            self.doc.documentLayout().draw(painter, ctx)

            painter.restore()

        def sizeHint(self, option, index):
            return Qg.QSize(self.doc.idealWidth(), self.doc.size().height())


# UPDATE DATABASE DIALOG WITH PROGRESS SHOWN
class UpdateDialogWindow(Qw.QDialog):
    icon_theme_signal = Qc.pyqtSignal(str)
    window_close_signal = Qc.pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.values = dict()
        self.last_signal = ''
        self.settings = Qc.QSettings(CONFIG_PATH, Qc.QSettings.IniFormat)
        self.init_ui()

    def __setitem__(self, k, v):
        self.values[k] = v

    def __getitem__(self, k):
        return None if k not in self.values else self.values[k]

    def init_ui(self):
        self.setWindowTitle('Database Update')

        self.exclud_dirs = ' '.join(self.parent().setting_params['directories_excluded'])
        combobox_text = self.parent().setting_params['icon_theme']

        self.icon_theme_label = Qw.QLabel('icon theme:')
        self.icon_theme_combobox = Qw.QComboBox(self)
        self.icon_theme_combobox.addItems([
            'adwaita', 'breeze', 'elementary', 'faenza', 'numix', 'oxygen',
            'paper', 'ubuntu'
        ])
        self.icon_theme_combobox.setEditable(True)
        self.icon_theme_combobox.lineEdit().setReadOnly(True)
        self.icon_theme_combobox.lineEdit().setAlignment(Qc.Qt.AlignCenter)
        for x in range(self.icon_theme_combobox.count()):
            self.icon_theme_combobox.setItemData(x, Qc.Qt.AlignCenter,
                                                 Qc.Qt.TextAlignmentRole)

        self.icon_theme_combobox.activated[str].connect(self.combo_box_change)

        index = self.icon_theme_combobox.findText(combobox_text)
        if index >= 0:
            self.icon_theme_combobox.setCurrentIndex(index)

        self.excluded_label = Qw.QLabel('ignored directories:')
        self.excluded_dirs_btn = Qw.QPushButton(self.exclud_dirs)
        self.crawl0_label = Qw.QLabel('progress:')
        self.crawl_label = Qw.QLabel('')
        self.label_1 = Qw.QLabel('• crawling the file system')
        self.label_2 = Qw.QLabel('• creating new database')
        self.label_3 = Qw.QLabel('• replacing old database')
        self.OK_button = Qw.QPushButton('Update')
        self.cancel_button = Qw.QPushButton('Cancel')

        if self.exclud_dirs == '':
            self.excluded_dirs_btn.setText('none')
            self.excluded_dirs_btn.setStyleSheet('color:#888;font: italic;')

        # MOON, 2023-12-31
        # print(FTS5_AVAILABLE) # True
        if FTS5_AVAILABLE:
            self.label_2.setToolTip('FTS5 Available')
        else:
            self.label_2.setToolTip('FTS4 Available')

        self.label_1.setIndent(70)
        self.label_2.setIndent(70)
        self.label_3.setIndent(70)

        self.crawl_label.setMinimumWidth(170)
        self.excluded_dirs_btn.setMaximumWidth(170)

        self.excluded_dirs_btn.clicked.connect(self.exclude_dialog)

        # TO MAKE SQUARE BRACKETS NOTATION WORK LATER ON
        # ALSO THE REASON FOR CUSTOM __getitem__ & __setitem__
        self['label_1'] = self.label_1
        self['label_2'] = self.label_2
        self['label_3'] = self.label_3

        grid = Qw.QGridLayout()
        grid.setSpacing(7)
        grid.addWidget(self.icon_theme_label, 0, 0)
        grid.addWidget(self.icon_theme_combobox, 0, 1)
        grid.addWidget(self.excluded_label, 1, 0)
        grid.addWidget(self.excluded_dirs_btn, 1, 1)
        grid.addWidget(self.crawl0_label, 2, 0)
        grid.addWidget(self.crawl_label, 2, 1)
        grid.addWidget(self.label_1, 3, 0, 1, 2)
        grid.addWidget(self.label_2, 4, 0, 1, 2)
        grid.addWidget(self.label_3, 5, 0, 1, 2)
        grid.addWidget(self.OK_button, 6, 0)
        grid.addWidget(self.cancel_button, 6, 1)
        self.setLayout(grid)

        self.OK_button.clicked.connect(self.clicked_OK_update_db)
        self.cancel_button.clicked.connect(self.clicked_cancel)

        self.OK_button.setFocus()

    def combo_box_change(self, text):
        self.icon_theme_signal.emit(text)

    def exclude_dialog(self):
        text, ok = Qw.QInputDialog.getText(
            self, '~/.config/angrysearch/', 'Directories to be ignored:',
            Qw.QLineEdit.Normal, self.exclud_dirs)
        if ok:
            text = text.strip()
            self.exclud_dirs = text
            self.settings.setValue('directories_excluded', text)
            self.parent().setting_params['directories_excluded'] = text.strip().split()
            if text == '':
                self.excluded_dirs_btn.setText('none')
                self.excluded_dirs_btn.setStyleSheet('color:#888;'
                                                     'font:italic;')
            else:
                self.excluded_dirs_btn.setText(text)
                self.excluded_dirs_btn.setStyleSheet('')
            self.OK_button.setFocus()

    def clicked_cancel(self):
        self.window_close_signal.emit('update_win_cancel')
        self.accept()

    def clicked_OK_update_db(self):
        self.OK_button.setDisabled(True)

        mounts_needed = self.parent().setting_params['conditional_mounts_for_autoupdate']

        missing_mount = False
        missing_mounts_list = []

        for x in mounts_needed:
            if not os.path.ismount(x):
                missing_mount = True
                missing_mounts_list.append(x)

        if missing_mount:
            m = ''
            for x in missing_mounts_list:
                m = m + '&nbsp;&nbsp;&nbsp;&nbsp;<b>' + x + '</b><br>'
            n = 'Mounts missing:<br>' + m + 'Do You want to update anyway?'
            reply = Qw.QMessageBox.question(
                self, 'Message', n, Qw.QMessageBox.Yes | Qw.QMessageBox.No)

            if reply == Qw.QMessageBox.No:
                self.accept()
                return

        self.thread_updating = ThreadDBUpdate(
            self.parent().setting_params['angrysearch_lite'],
            self.parent().setting_params['directories_excluded'])

        self.thread_updating.db_update_signal.connect(
            self.upd_dialog_receives_signal, Qc.Qt.QueuedConnection)

        self.thread_updating.crawl_signal.connect(
            self.upd_dialog_receives_crawl, Qc.Qt.QueuedConnection)

        self.thread_updating.start()

    def upd_dialog_receives_signal(self, message, time):
        if message == 'the_end_of_the_update':
            self.window_close_signal.emit('update_win_ok')
            self.accept()
            return

        label = self[message]
        label_alt = '➔{}'.format(label.text()[1:])
        label.setText(label_alt)

        if self.last_signal:
            prev_label = self[self.last_signal]
            prev_label_alt = '✔{} - {}'.format(prev_label.text()[1:], time)
            prev_label.setText(prev_label_alt)

        self.last_signal = message

    def upd_dialog_receives_crawl(self, message):
        self.crawl_label.setText(message)


def open_database():
    global DATABASE_PATH
    if os.path.exists(DATABASE_PATH):
        return sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    else:
        temp = TEMP_PATH + '/angry_database.db'
        if os.path.exists(temp):
            os.remove(temp)
        return sqlite3.connect(temp, check_same_thread=False)


# CUSTOM REGEX FUNCTION FOR SQLITE TO ALLOW REGEX SEARCH MODE
def regexp(expr, item):
    name = item.split('/')[-1]
    r = re.compile(expr, re.IGNORECASE)
    return r.search(name) is not None


def main():
    global con
    with open_database() as con:
        con.create_function("regexp", 2, regexp)
        app = Qw.QApplication(sys.argv)
        ui = AngryMainWindow()
        sys.exit(app.exec_())


if __name__ == '__main__':
    main()
