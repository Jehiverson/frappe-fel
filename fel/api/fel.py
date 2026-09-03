import frappe

from kingo_fel.services.certification import create_pending_fel_document
from kingo_fel.providers.registry import get_provider
from kingo_fel.services.certification import get_company_fel_settings
from kingo_fel.services.nuc_json import build_fact_nuc_json
from kingo_fel.services.certification import (
    certify_fel_document as certify_fel_document_service,
)
from kingo_fel.services.nuc_xml import build_fact_nuc_xml

@frappe.whitelist()
def prepare_fel_document(sales_invoice_name: str):
    """Prepara el expediente FEL de una Factura de Venta."""

    if not sales_invoice_name:
        frappe.throw("Debe indicar la Factura de Venta.")

    invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)

    if not frappe.has_permission("Sales Invoice", "write", invoice):
        frappe.throw(
            f"No tiene permiso para solicitar FEL para la factura '{sales_invoice_name}'."
        )

    fel_document = create_pending_fel_document(sales_invoice_name)

    return {
        "success": True,
        "message": "Expediente FEL preparado correctamente.",
        "fel_document_id": fel_document.name,
        "fel_status": fel_document.fel_status,
        "provider": fel_document.fel_provider,
        "sales_invoice": fel_document.sales_invoice,
    }

@frappe.whitelist()
def test_digifact_connection(company: str):
    if not company:
        frappe.throw("La compañía es obligatoria.")

    settings = get_company_fel_settings(company)
    provider = get_provider(settings)

    return provider.test_connection()

@frappe.whitelist()
def preview_digifact_nuc(sales_invoice_name: str):
    if not sales_invoice_name:
        frappe.throw("La factura de venta es obligatoria.")

    invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)

    if not frappe.has_permission("Sales Invoice", "read", invoice):
        frappe.throw("No tienes permiso para ver esta factura.")

    settings = get_company_fel_settings(invoice.company)

    if settings.fel_provider != "digifact":
        frappe.throw("La vista previa NUC actual solo está disponible para Digifact.")

    return {
        "success": True,
        "sales_invoice": invoice.name,
        "nuc": build_fact_nuc_json(invoice, settings),
    }

@frappe.whitelist()
def certify_fel_document(fel_document_name: str):
    if not fel_document_name:
        frappe.throw("El documento FEL es obligatorio.")

    fel_document = frappe.get_doc("FEL Document", fel_document_name)
    invoice = frappe.get_doc("Sales Invoice", fel_document.sales_invoice)

    if not frappe.has_permission("Sales Invoice", "submit", invoice):
        frappe.throw("No tienes permiso para enviar esta Factura de Venta.")

    result = certify_fel_document_service(fel_document_name)
    certified_document = result["fel_document"]

    return {
        "success": certified_document.fel_status == "Certificado",
        "fel_document_id": certified_document.name,
        "sales_invoice": certified_document.sales_invoice,
        "fel_status": certified_document.fel_status,
        "certification_uuid": certified_document.certification_uuid,
        "fel_series": certified_document.fel_series,
        "fel_number": certified_document.fel_number,
        "invoice_submitted": result["invoice_submitted"],
        "message": result["message"],
    }

@frappe.whitelist()
def preview_digifact_nuc_xml(sales_invoice_name: str):
    if not sales_invoice_name:
        frappe.throw("La factura de venta es obligatoria.")

    invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)

    if not frappe.has_permission("Sales Invoice", "read", invoice):
        frappe.throw("No tienes permiso para ver esta factura.")

    settings = get_company_fel_settings(invoice.company)

    if settings.fel_provider != "digifact":
        frappe.throw("La vista previa XML actual solo está disponible para Digifact.")

    return {
        "success": True,
        "sales_invoice": invoice.name,
        "xml": build_fact_nuc_xml(invoice, settings),
    }