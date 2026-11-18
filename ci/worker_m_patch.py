"""Build a research-only OXT with a candidate focused-edit notification."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "src/sheet_manager/uno_rename_dialog.py"
source = path.read_text(encoding="utf-8")
anchor = '        self._control("status").getModel().Label = status\n'
addition = '''        if found[self._row].startswith("Another sheet"):
            peer = self._control("name").getPeer()
            announced_name = "New name: " + found[self._row]
            if peer.getProperty("AccessibleName") != announced_name:
                peer.setProperty("AccessibleName", announced_name)
'''
assert source.count(anchor) == 1
path.write_text(source.replace(anchor, anchor + addition), encoding="utf-8")
