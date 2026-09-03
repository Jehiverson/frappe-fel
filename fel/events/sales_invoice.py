import frappe


def block_direct_submission(doc, method=None):
    """
    Impide enviar una Sales Invoice de una compañía FEL activa sin
    un DTE certificado previamente.
    """

    # El servicio FEL marca temporalmente el documento antes de enviarlo.
    if doc.flags.get("fel_certification_submission"):
        return

    fel_enabled = frappe.db.exists(
        "FEL Company Settings",
        {
            "company": doc.company,
            "enabled": 1,
        },
    )

    # Compañías sin FEL habilitado mantienen el comportamiento normal.
    if not fel_enabled:
        return

    certified_document = frappe.db.exists(
        "FEL Document",
        {
            "sales_invoice": doc.name,
            "fel_status": "Certificado",
        },
    )

    # Si ya existe el DTE, permitimos reintentar el envío local.
    if certified_document:
        return

    frappe.throw(
        "Esta factura debe emitirse mediante FEL. "
        "Usa la acción 'Emitir factura FEL' para certificarla antes de validarla."
    )