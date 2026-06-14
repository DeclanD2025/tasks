"""Login / unlock screen.

Full-bleed star-field with the Orion constellation subtly highlighted, and a
centred dark glass card holding the ORION wordmark, the tagline, and the unlock
form. Cinematic and minimal — no clutter.

The unlock check is delegated to `core.security.verify_unlock`. In development
the default passphrase is "orion" (see README).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtGui import QColor

from app.core.security import verify_unlock
from app.ui.components.constellation import ConstellationBackground
from app.ui.components.widgets import OrionLogo
from app.ui.themes.theme import PALETTE, TYPE


class LoginScreen(QWidget):
    unlocked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoginScreen")

        # Full-bleed animated star field with Orion highlighted.
        self._bg = ConstellationBackground(self, density=260, dim=1.0,
                                           orion_anchor=(0.30, 0.46))

        # Centred glass card.
        self._card = QWidget(self)
        self._card.setObjectName("GlassPanel")
        self._card.setFixedWidth(380)
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(60)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 16)
        self._card.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self._card)
        lay.setContentsMargins(34, 36, 34, 30)
        lay.setSpacing(16)
        lay.setAlignment(Qt.AlignTop)

        lay.addWidget(OrionLogo(big=True, tagline=True))

        prompt = QLabel("Authenticate to enter the command centre.")
        prompt.setObjectName("Faint")
        prompt.setWordWrap(True)
        lay.addWidget(prompt)

        self._email = QLineEdit()
        self._email.setPlaceholderText("operator@orion.local")
        lay.addWidget(self._email)

        self._pw = QLineEdit()
        self._pw.setPlaceholderText("Unlock passphrase")
        self._pw.setEchoMode(QLineEdit.Password)
        self._pw.returnPressed.connect(self._attempt)
        lay.addWidget(self._pw)

        self._error = QLabel("")
        self._error.setStyleSheet(f"color:{PALETTE.critical}; font-size:{TYPE.small}px;")
        self._error.setVisible(False)
        lay.addWidget(self._error)

        btn = QPushButton("ENTER ORION")
        btn.setObjectName("PrimaryButton")
        btn.clicked.connect(self._attempt)
        lay.addWidget(btn)

        hint = QLabel("Local-first · No cloud dependency")
        hint.setObjectName("Faint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color:{PALETTE.text_faint}; font-size:{TYPE.micro}px;")
        lay.addWidget(hint)

    def resizeEvent(self, event):  # noqa: N802
        self._bg.setGeometry(self.rect())
        cw, ch = self._card.width(), self._card.sizeHint().height()
        self._card.setGeometry(
            (self.width() - cw) // 2, (self.height() - ch) // 2, cw, ch
        )
        super().resizeEvent(event)

    def _attempt(self) -> None:
        if verify_unlock(self._pw.text()):
            self._error.setVisible(False)
            self.unlocked.emit()
        else:
            self._error.setText("Authentication failed. Try the demo passphrase: orion")
            self._error.setVisible(True)
