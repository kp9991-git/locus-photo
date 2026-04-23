import os
import platform
import logging
from pathlib import Path
import sys
import shutil
import yaml
from PySide6.QtWidgets import QFileDialog
from viewer.core.constants import APP_NAME

class ConfigMixin:
    # ── Config & directories ──────────────────────────────────────────

    def process_dir(self, value):
        if value == "$$$PICTURES$$$":
            system = platform.system()
            if system == 'Windows':
                res = os.path.join(Path(os.environ['USERPROFILE']), 'Pictures')
                if not os.path.exists(res):
                    res = os.path.join(os.path.join(Path(os.environ['USERPROFILE']), 'OneDrive'), 'Pictures')
            elif system == 'Darwin' or system == 'Linux':
                res = os.path.join(Path.home(), 'Pictures')
            else:
                if self.logger:
                    self.logger.error("Unknown system: {}".format(system))
                res = ""
        elif '$$$USERNAME$$$' in value:
            res = value.replace('$$$USERNAME$$$', os.environ.get('USERNAME', ''))
        else:
            res = value
        if not os.path.exists(res):
            return None
        return res

    @staticmethod
    def get_config_fpath(copy_local=False):
        fname_key = APP_NAME.lower().replace(" ", "-")
        home_path = os.path.join(Path.home(), ".{}-config.yaml".format(fname_key))
        if os.path.exists(home_path):
            return home_path
        if getattr(sys, 'frozen', False):
            res = os.path.join(sys._MEIPASS, ".{}-config.yaml".format(fname_key))
        else:
            res = os.path.join(os.getcwd(), '.{}-config.yaml'.format(fname_key))
        if copy_local:
            try:
                shutil.copy(res, home_path)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Could not copy config from %s to %s",
                    res,
                    home_path,
                )
        if os.path.exists(home_path):
            return home_path
        return res

    @classmethod
    def is_file_acceptable(cls, file_path):
        try:
            file_size = os.path.getsize(file_path)
            ext = os.path.splitext(file_path)[1].lower()
            return file_size <= cls.MAX_FILE_SIZE and (cls.SUPPORTED_EXTENSIONS is None or ext in cls.SUPPORTED_EXTENSIONS)
        except OSError:
            return False

    def save_config(self):
        config_fpath = self.get_config_fpath(copy_local=True)
        temp_fpath = "{}.tmp".format(config_fpath)
        try:
            with open(temp_fpath, 'w', encoding='utf-8') as file:
                yaml.dump(self.config, file, default_flow_style=False)
            os.replace(temp_fpath, config_fpath)
        except Exception:
            if os.path.exists(temp_fpath):
                try:
                    os.remove(temp_fpath)
                except Exception:
                    pass
            if self.logger:
                self.logger.exception("Failed to save config to %s", config_fpath)
            else:
                logging.getLogger(__name__).exception("Failed to save config to %s", config_fpath)

    def get_data_dir(self, get_index=False):
        for i, (label, dir_) in enumerate(zip(self.config['base_dir_labels'], self.config['base_dirs'])):
            if label == self.config['base_dir_selected_label']:
                return i if get_index else self.process_dir(dir_)
        raise ValueError("Could not find selected dir for label {}".format(self.config['base_dir_selected_label']))

    def get_combobox_items(self):
        return self.config['base_dir_labels'] + [self.ADD_DIR_LABEL, self.REMOVE_DIR_LABEL]

    # ── Directory management ──────────────────────────────────────────

    def base_dir_add(self):
        fpath = QFileDialog.getExistingDirectory(self.root, "Select Directory")
        if len(fpath) > 0:
            dir_path = str(Path(fpath))
            dir_label = os.path.basename(dir_path.rstrip("\\/")) or dir_path
            dir_label_ = dir_label
            i = 1
            while dir_label_ in self.config['base_dir_labels']:
                dir_label_ = dir_label + " ({})".format(i)
                i += 1
            self.config['base_dirs'].append(dir_path)
            self.config['base_dir_labels'].append(dir_label_)
            self.config['base_dir_selected_label'] = dir_label_
            self.combobox.blockSignals(True)
            self.combobox.clear()
            self.combobox.addItems(self.get_combobox_items())
            self.combobox.setCurrentText(dir_label_)
            self.combobox.blockSignals(False)
            self.update_tree()
            self.save_config()

    def base_dir_remove(self):
        if len(self.config['base_dirs']) > 1:
            selected_item_index = self.get_data_dir(get_index=True)
            new_selected_index = max(0, selected_item_index - 1)
            selected_item = self.config['base_dir_labels'][new_selected_index]
            self.config['base_dir_selected_label'] = selected_item
            self.config['base_dirs'].pop(selected_item_index)
            self.config['base_dir_labels'].pop(selected_item_index)
            self.combobox.blockSignals(True)
            self.combobox.clear()
            self.combobox.addItems(self.get_combobox_items())
            self.combobox.setCurrentText(selected_item)
            self.combobox.blockSignals(False)
            self.update_tree()
            self.save_config()

