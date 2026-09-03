from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CertificationResult:
    """Resultado normalizado que devuelve cualquier certificador FEL."""

    status: str
    provider: str
    uuid: str | None = None
    series: str | None = None
    number: str | None = None
    certified_at: str | None = None
    xml_content: str | None = None
    pdf_content: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


class FelProvider(ABC):
    """Contrato que debe implementar cada certificador FEL."""

    provider_code: str

    def __init__(self, company_settings):
        self.company_settings = company_settings

    @abstractmethod
    def certify(self, fel_document) -> CertificationResult:
        """Envía un DTE al certificador y devuelve el resultado normalizado."""

    @abstractmethod
    def cancel(self, fel_document, reason: str) -> CertificationResult:
        """Solicita la anulación de un DTE certificado."""

    @abstractmethod
    def get_document(self, uuid: str) -> CertificationResult:
        """Consulta un DTE previamente certificado."""