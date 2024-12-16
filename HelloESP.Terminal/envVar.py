import os
from typing import Optional


class EnvVarHandler:
    def __init__(self):
        self._idf_path: Optional[str] = None

    @property
    def idf_path(self) -> Optional[str]:
        """
        Ottiene il valore della variabile d'ambiente IDF_PATH.

        Returns:
            str | None: Il valore di IDF_PATH se esiste, altrimenti None
        """
        if self._idf_path is None:
            self._idf_path = os.getenv('IDF_PATH')
        return self._idf_path

    @idf_path.setter
    def idf_path(self, value: str) -> None:
        """
        Imposta il valore della variabile d'ambiente IDF_PATH.

        Args:
            value (str): Il nuovo valore per IDF_PATH
        """
        os.environ['IDF_PATH'] = value
        self._idf_path = value

    def reset_idf_path(self) -> None:
        """
        Resetta il valore cached di IDF_PATH forzando una rilettura
        dalla variabile d'ambiente al prossimo accesso.
        """
        self._idf_path = None

    def validate_idf_path(self) -> bool:
        """
        Verifica se IDF_PATH è impostato e punta a una directory valida.

        Returns:
            bool: True se IDF_PATH è valido, False altrimenti
        """
        path = self.idf_path
        return path is not None and os.path.isdir(path)