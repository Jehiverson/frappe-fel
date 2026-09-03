from __future__ import annotations

import base64
import json
from urllib.parse import urlparse

import frappe
from frappe.utils import get_url_to_form
from frappe.utils.file_manager import save_file

from fel.providers.registry import get_provider


def get_company_fel_settings(company: str):
    settings_name = frappe.db.get_value(
        "FEL Company Settings",
        {"company": company},
        "name",
    )

    if not settings_name:
        frappe.throw(f"La compañía '{company}' no tiene configuración FEL.")

    settings = frappe.get_doc("FEL Company Settings", settings_name)

    if not settings.enabled:
        frappe.throw(f"FEL está deshabilitado para la compañía '{company}'.")

    return settings


def create_pending_fel_document(sales_invoice_name: str, dte_type: str = "FACT"):
    invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)

    if invoice.docstatus != 0:
        frappe.throw(
            "La factura debe estar en borrador antes de solicitar certificación FEL."
        )

    settings = get_company_fel_settings(invoice.company)

    existing_document = frappe.db.get_value(
        "FEL Document",
        {"sales_invoice": invoice.name, "dte_type": dte_type},
        "name",
    )

    if existing_document:
        return frappe.get_doc("FEL Document", existing_document)

    fel_document = frappe.get_doc(
        {
            "doctype": "FEL Document",
            "company": invoice.company,
            "sales_invoice": invoice.name,
            "dte_type": dte_type,
            "fel_provider": settings.fel_provider,
            "fel_status": "Pendiente",
        }
    )
    fel_document.insert(ignore_permissions=True)

    return fel_document


def _save_certificate_file(fel_document, file_name: str, encoded_content: str):
    if not encoded_content:
        return None

    content = base64.b64decode(encoded_content)

    file_doc = save_file(
        file_name,
        content,
        "FEL Document",
        fel_document.name,
        is_private=1,
    )

    return file_doc.file_url


def _provider_response_text(response: dict) -> str:
    return json.dumps(
        response or {},
        ensure_ascii=False,
        default=str,
    )


def certify_fel_document(fel_document_name: str):
    fel_document = frappe.get_doc("FEL Document", fel_document_name)

    if fel_document.fel_status == "Certificado":
        return {
            "fel_document": fel_document,
            "invoice_submitted": frappe.db.get_value(
                "Sales Invoice",
                fel_document.sales_invoice,
                "docstatus",
            )
            == 1,
            "message": "Este DTE ya fue certificado.",
        }

    if fel_document.fel_status == "Anulado":
        frappe.throw("No se puede certificar un DTE que ya fue anulado.")

    if fel_document.fel_status == "Enviando":
        frappe.throw(
            "Este DTE está en estado Enviando. "
            "Primero debe consultarse antes de reenviarlo."
        )

    invoice = frappe.get_doc("Sales Invoice", fel_document.sales_invoice)

    if invoice.docstatus != 0:
        frappe.throw("La Factura de Venta debe estar en borrador.")

    settings = get_company_fel_settings(invoice.company)

    if fel_document.company != invoice.company:
        frappe.throw("La compañía del DTE no coincide con la de la factura.")

    if fel_document.fel_provider != settings.fel_provider:
        frappe.throw(
            "El certificador del DTE no coincide con la configuración de la compañía."
        )

    fel_document.db_set("fel_status", "Enviando", update_modified=False)
    fel_document.db_set("error_message", None, update_modified=False)

    provider = get_provider(settings)
    result = provider.certify(fel_document)

    fel_document.reload()
    fel_document.provider_response = _provider_response_text(result.raw_response)

    if result.status == "pending":
        fel_document.fel_status = "Enviando"
        fel_document.error_message = result.error_message
        fel_document.save(ignore_permissions=True)

        return {
            "fel_document": fel_document,
            "invoice_submitted": False,
            "message": result.error_message,
        }

    if result.status != "certified":
        fel_document.fel_status = "Rechazado"
        fel_document.error_message = result.error_message
        fel_document.save(ignore_permissions=True)

        return {
            "fel_document": fel_document,
            "invoice_submitted": False,
            "message": result.error_message,
        }

    xml_url = _save_certificate_file(
        fel_document,
        f"{invoice.name}-{result.uuid}.xml",
        result.xml_content,
    )
    pdf_url = _save_certificate_file(
        fel_document,
        f"{invoice.name}-{result.uuid}.pdf",
        result.pdf_content,
    )

    fel_document.fel_status = "Certificado"
    fel_document.certification_uuid = result.uuid
    fel_document.fel_series = result.series
    fel_document.fel_number = result.number
    fel_document.certified_at = result.certified_at
    fel_document.certified_xml = xml_url
    fel_document.certified_pdf = pdf_url
    fel_document.error_message = None
    fel_document.save(ignore_permissions=True)

    # Deja trazabilidad visible desde la misma Factura de Venta, sin obligar
    # al usuario a buscar el expediente técnico FEL en otro módulo.
    # get_url_to_form usa el nombre interno del sitio (`frontend`) en Docker.
    # Conservamos solo la ruta para que el enlace se abra en el host/browser
    # que el usuario está usando (por ejemplo, localhost:8080).
    fel_url = urlparse(
        get_url_to_form("FEL Document", fel_document.name)
    ).path
    pdf_link = ""

    if fel_document.certified_pdf:
        pdf_link = (
            f' · <a href="{fel_document.certified_pdf}" target="_blank">'
            "Abrir PDF certificado</a>"
        )

    invoice.add_comment(
        "Info",
        (
            "Factura certificada FEL. "
            f"UUID: {fel_document.certification_uuid}. "
            f"Serie: {fel_document.fel_series}. "
            f"Número: {fel_document.fel_number}. "
            f'<a href="{fel_url}">Abrir expediente FEL</a>{pdf_link}'
        ),
    )

    try:
        invoice.flags.fel_certification_submission = True
        invoice.submit()
    except Exception:
        frappe.log_error(
            title="FEL certificado, pero no se pudo enviar la Factura de Venta",
            message=frappe.get_traceback(),
        )

        fel_document.error_message = (
            "El DTE fue certificado, pero ERPNext no pudo enviar la Factura de Venta. "
            "No intentes certificarlo de nuevo; revisa y resuelve el envío local."
        )
        fel_document.save(ignore_permissions=True)

        return {
            "fel_document": fel_document,
            "invoice_submitted": False,
            "message": fel_document.error_message,
        }

    return {
        "fel_document": fel_document,
        "invoice_submitted": True,
        "message": "DTE certificado y Factura de Venta enviada correctamente.",
    }
