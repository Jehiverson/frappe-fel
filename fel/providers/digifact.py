import re
import frappe
import requests

from kingo_fel.providers.base import CertificationResult, FelProvider


class DigifactProvider(FelProvider):
    """Adaptador técnico para Digifact Guatemala."""

    provider_code = "digifact"

    TEST_BASE_URL = "https://testnucgt.digifact.com/api"
    PRODUCTION_BASE_URL = "https://nucgt.digifact.com/gt.com.apinuc/api"

    def _base_url(self):
        if self.company_settings.environment == "Pruebas":
            return self.TEST_BASE_URL

        return self.PRODUCTION_BASE_URL

    def _tax_id(self):
        tax_id = frappe.db.get_value(
            "Company", self.company_settings.company, "tax_id"
        )
        normalized_tax_id = re.sub(r"\D", "", str(tax_id or ""))

        if not normalized_tax_id:
            frappe.throw(
                f"La compañía '{self.company_settings.company}' no tiene ID Fiscal."
            )

        return normalized_tax_id.zfill(12)

    def _api_username(self):
        username = (self.company_settings.api_username or "").strip()

        if not username:
            frappe.throw("Falta configurar el Usuario API de Digifact.")

        if "." in username:
            frappe.throw(
                "Guarda únicamente el usuario corto de Digifact, por ejemplo USER_TEST."
            )

        return username

    def get_token(self):
        username = self._api_username()
        password = self.company_settings.get_password("api_password")

        if not password:
            frappe.throw("Falta configurar la Contraseña API de Digifact.")

        digifact_username = f"GT.{self._tax_id()}.{username}"

        try:
            response = requests.post(
                f"{self._base_url()}/login/get_token",
                json={
                    "Username": digifact_username,
                    "Password": password,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            frappe.throw(
                "No fue posible conectar con Digifact. "
                "Revisa las credenciales, el ambiente y la conexión de red."
            )

        token = payload.get("token") or payload.get("Token")

        if not token:
            provider_message = (
                payload.get("message")
                or payload.get("Message")
                or payload.get("Mensaje")
                or "Sin detalle proporcionado por Digifact."
            )
            provider_code = (
                payload.get("code")
                or payload.get("Code")
                or payload.get("Codigo")
                or "SIN_CODIGO"
            )

            frappe.throw(
                "Digifact no devolvió un token "
                f"(código: {provider_code}). Mensaje: {provider_message}"
            )

        return token

    def test_connection(self):
        self.get_token()

        return {
            "success": True,
            "provider": self.provider_code,
            "environment": self.company_settings.environment,
            "message": "Conexión con Digifact validada correctamente.",
        }

    def certify(self, fel_document) -> CertificationResult:
        from kingo_fel.services.nuc_json import build_fact_nuc_json

        invoice = frappe.get_doc("Sales Invoice", fel_document.sales_invoice)
        nuc = build_fact_nuc_json(invoice, self.company_settings)

        try:
            response = requests.post(
                f"{self._base_url()}/v2/transform/nuc_json",
                params={
                    "TAXID": self._tax_id(),
                    # Guardamos ambos comprobantes certificados en el expediente FEL.
                    "FORMAT": "XML|PDF",
                    "USERNAME": self._api_username(),
                },
                headers={
                    "Authorization": self.get_token(),
                    "Content-Type": "application/json",
                },
                # `json=` serializa el cuerpo igual que axios.post(url, nuc).
                json=nuc,
                timeout=90,
            )
        except requests.RequestException:
            # No sabemos si Digifact recibió o no el DTE. No se debe reintentar a ciegas.
            return CertificationResult(
                status="pending",
                provider=self.provider_code,
                error_code="CONNECTION_UNKNOWN",
                error_message=(
                    "No hubo confirmación de Digifact. "
                    "Consulta el estado antes de intentar enviar nuevamente."
                ),
            )

        try:
            payload = response.json()
        except ValueError:
            return CertificationResult(
                status="rejected",
                provider=self.provider_code,
                error_code=f"HTTP_{response.status_code}",
                error_message="Digifact devolvió una respuesta que no es JSON.",
            )

        # No guardamos XML/PDF base64 en provider_response: se adjuntan como archivos.
        safe_response = {
            key: value
            for key, value in payload.items()
            if key not in {"responseData1", "responseData2", "responseData3"}
        }

        request_body = response.request.body or b""

        if isinstance(request_body, str):
            request_body = request_body.encode("utf-8")

        safe_response["_request_debug"] = {
            "endpoint": response.request.url.split("?")[0],
            "content_type": response.request.headers.get("Content-Type"),
            "content_length": response.request.headers.get("Content-Length"),
            "body_bytes": len(request_body),
        }

        if response.status_code != 200:
            return CertificationResult(
                status="rejected",
                provider=self.provider_code,
                error_code=str(response.status_code),
                error_message=(
                    payload.get("message")
                    or payload.get("description")
                    or "Digifact rechazó la solicitud."
                ),
                raw_response=safe_response,
            )

        if str(payload.get("code")) != "1" or not payload.get("authNumber"):
            return CertificationResult(
                status="rejected",
                provider=self.provider_code,
                error_code=str(payload.get("code") or "UNKNOWN"),
                error_message=(
                    payload.get("message")
                    or payload.get("description")
                    or "Digifact no certificó el DTE."
                ),
                raw_response=safe_response,
            )

        return CertificationResult(
            status="certified",
            provider=self.provider_code,
            uuid=payload.get("authNumber"),
            series=payload.get("batch"),
            number=payload.get("serial"),
            certified_at=payload.get("enrolledTimeStamp"),
            xml_content=payload.get("responseData1"),
            pdf_content=payload.get("responseData3"),
            raw_response=safe_response,
        )

    def cancel(self, fel_document, reason: str) -> CertificationResult:
        raise NotImplementedError("Pendiente: anular un DTE con Digifact.")

    def get_document(self, uuid: str) -> CertificationResult:
        raise NotImplementedError("Pendiente: consultar un DTE con Digifact.")
