from __future__ import annotations

import re
import uuid
from decimal import Decimal, ROUND_HALF_UP

import frappe


SIX_DECIMALS = Decimal("0.000001")


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _number(value) -> str:
    return format(
        _decimal(value).quantize(SIX_DECIMALS, rounding=ROUND_HALF_UP),
        "f",
    )


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _required_settings(settings):
    required_fields = {
        "iva_affiliation": "Afiliación IVA",
        "establishment_code": "Código de establecimiento",
        "establishment_name": "Nombre establecimiento",
        "establishment_address": "Dirección establecimiento",
        "establishment_postal_code": "Código postal",
        "establishment_district": "Municipio",
        "establishment_state": "Departamento",
        "phrase_type": "Tipo de frase",
        "phrase_scenario": "Escenario de frase",
    }

    for fieldname, label in required_fields.items():
        if not settings.get(fieldname):
            frappe.throw(f"Falta configurar '{label}' en FEL Company Settings.")


def _seller(company, settings):
    tax_id = _digits(company.tax_id)

    if not tax_id:
        frappe.throw(f"La compañía '{company.name}' no tiene ID Fiscal.")

    _required_settings(settings)

    seller = {
        # En el NUC/SAT el NIT debe ir en su forma tributaria real, sin
        # completar con ceros. El padding a 12 aplica únicamente al login y
        # al query parameter TAXID de Digifact.
        "TaxID": tax_id,
        "TaxIDAdditionalInfo": [
            {
                "Name": "AfiliacionIVA",
                "Data": None,
                "Value": settings.iva_affiliation,
            }
        ],
        "Name": company.company_name,
        "AdditionlInfo": [
            {
                "Name": "TipoFrase",
                "Data": str(settings.phrase_type),
                "Value": str(settings.phrase_type),
            },
            {
                "Name": "Escenario",
                "Data": str(settings.phrase_type),
                "Value": str(settings.phrase_scenario),
            },
        ],
        "BranchInfo": {
            "Code": str(settings.establishment_code),
            "Name": settings.establishment_name,
            "AddressInfo": {
                "Address": settings.establishment_address,
                "City": settings.establishment_postal_code,
                "District": settings.establishment_district,
                "State": settings.establishment_state,
                "Country": "GT",
            },
        },
    }

    # Contacto opcional, presente en la integración Fee ya certificada.
    company_email = company.get("email")
    if company_email:
        seller["Contact"] = {"EmailList": {"Email": [company_email]}}

    return seller


def _buyer(invoice):
    customer = frappe.get_doc("Customer", invoice.customer)
    raw_tax_id = str(customer.tax_id or "").strip().upper()
    address = {
        "Address": "CIUDAD",
        "City": "01001",
        "District": "GUATEMALA",
        "State": "GUATEMALA",
        "Country": "GT",
    }

    if not raw_tax_id or raw_tax_id == "CF":
        return {
            "TaxID": "CF",
            "Name": "CONSUMIDOR FINAL",
            "AddressInfo": address,
        }

    tax_id = _digits(raw_tax_id)

    if not tax_id:
        frappe.throw(
            f"El ID Fiscal del cliente '{customer.name}' no contiene un NIT o CUI válido."
        )

    buyer = {
        "TaxID": tax_id,
        "Name": customer.customer_name,
        "AddressInfo": address,
    }

    # Por ahora inferimos CUI por sus 13 dígitos.
    if len(tax_id) == 13:
        buyer["TaxIDType"] = "CUI"

    return buyer


def _issue_datetime(invoice):
    posting_date = str(invoice.posting_date)
    posting_time = str(invoice.posting_time or "00:00:00").split(".")[0]
    # Frappe puede serializar un campo Time como "2:28:16".  Digifact
    # valida RFC 3339 estrictamente y requiere "02:28:16".
    time_parts = posting_time.split(":")
    if len(time_parts) != 3:
        frappe.throw("La hora de contabilización de la factura no es válida para FEL.")

    hour, minute, second = (part.zfill(2) for part in time_parts)
    return f"{posting_date}T{hour}:{minute}:{second}-06:00"


def _item_type(item_code):
    is_stock_item = frappe.db.get_value("Item", item_code, "is_stock_item")
    return "Bien" if is_stock_item else "Servicio"


def _number_in_words_quetzales(amount) -> str:
    """Texto informativo de la adenda; no participa en el cálculo fiscal."""
    units = (
        "", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE",
        "OCHO", "NUEVE", "DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE",
        "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE",
    )
    tens = (
        "", "", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA",
        "SETENTA", "OCHENTA", "NOVENTA",
    )
    hundreds = (
        "", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS",
        "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS",
    )

    def under_hundred(number):
        if number < 20:
            return units[number]
        if number < 30:
            return "VEINTE" if number == 20 else f"VEINTI{units[number - 20]}"
        ten, unit = divmod(number, 10)
        return tens[ten] if not unit else f"{tens[ten]} Y {units[unit]}"

    def under_thousand(number):
        if number == 0:
            return ""
        if number == 100:
            return "CIEN"
        hundred, remainder = divmod(number, 100)
        return " ".join(
            value for value in (hundreds[hundred], under_hundred(remainder)) if value
        )

    rounded = _decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer = int(rounded)
    cents = int((rounded - integer) * 100)
    thousands, remainder = divmod(integer, 1000)

    if integer == 0:
        words = "CERO"
    else:
        parts = []
        if thousands:
            parts.append("MIL" if thousands == 1 else f"{under_thousand(thousands)} MIL")
        if remainder:
            parts.append(under_thousand(remainder))
        words = " ".join(parts).strip()

    if words.endswith("UNO"):
        words = f"{words[:-3]}UN"

    return f"{words} QUETZALES CON {cents:02d}/100"


def _items_and_taxes(invoice):
    if not invoice.items:
        frappe.throw("La factura debe tener al menos un producto.")

    if not invoice.taxes:
        frappe.throw("La factura debe tener IVA antes de generar el DTE.")

    total_tax = _decimal(invoice.total_taxes_and_charges)
    net_total = sum(_decimal(item.net_amount) for item in invoice.items)

    if net_total <= 0:
        frappe.throw("El total neto de la factura debe ser mayor a cero.")

    if total_tax < 0:
        frappe.throw("Esta primera versión no admite impuestos negativos.")

    items = []
    allocated_tax = Decimal("0")

    for index, row in enumerate(invoice.items, start=1):
        net_amount = _decimal(row.net_amount)
        quantity = _decimal(row.qty)
        discount = _decimal(row.discount_amount) * quantity

        if index == len(invoice.items):
            item_tax = total_tax - allocated_tax
        else:
            item_tax = (
                total_tax * net_amount / net_total
            ).quantize(SIX_DECIMALS, rounding=ROUND_HALF_UP)
            allocated_tax += item_tax

        item_type = _item_type(row.item_code)
        payload = {
            "Number": str(index),
            "Codes": None,
            "Type": item_type,
            "Description": row.item_name or row.description or row.item_code,
            "Qty": _number(quantity),
            "UnitOfMeasure": "UNI" if item_type == "Bien" else "SER",
            "Price": _number(row.rate),
            "Discounts": (
                {
                    "Discount": [
                        {
                            "Amount": _number(discount),
                        }
                    ]
                }
                if discount > 0
                else None
            ),
            "Taxes": {
                "Tax": [
                    {
                        "Code": "1",
                        "Description": "IVA",
                        "TaxableAmount": _number(net_amount),
                        "Amount": _number(item_tax),
                    }
                ]
            },
            "Totals": {
                "TotalItem": _number(net_amount + item_tax),
            },
        }

        items.append(payload)

    return items, total_tax


def build_fact_nuc_json(invoice, settings):
    if invoice.docstatus != 0:
        frappe.throw(
            "La factura debe estar en borrador para preparar su DTE FEL."
        )

    company = frappe.get_doc("Company", invoice.company)
    items, total_tax = _items_and_taxes(invoice)

    # Referencia estable: la misma factura siempre produce la misma adenda.
    adenda_code = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"kingo-fel:{invoice.name}")
    ).upper()

    return {
        "Version": "1.00",
        "CountryCode": "GT",
        "Header": {
            "DocType": "FACT",
            "IssuedDateTime": _issue_datetime(invoice),
            "Currency": invoice.currency,
        },
        "Seller": _seller(company, settings),
        "Buyer": _buyer(invoice),
        "ThirdParties": None,
        "Items": items,
        "Totals": {
            "TotalTaxes": {
                "TotalTax": [
                    {
                        "Description": "IVA",
                        "Amount": _number(total_tax),
                    }
                ]
            },
            "GrandTotal": {
                "InvoiceTotal": _number(invoice.grand_total),
            },
        },
        "AdditionalDocumentInfo": {
            "AdditionalInfo": [
                {
                    "Code": adenda_code,
                    "Type": "ADENDA",
                    "AditionalData": {
                        "Data": [
                            {
                                "Name": "INFORMACION_ADICIONAL",
                                "Info": [
                                    {
                                        "Name": "OBSERVACIONES",
                                        "Data": None,
                                        "Value": "-",
                                    },
                                    {
                                        "Name": "CANTIDAD_LETRAS",
                                        "Data": None,
                                        "Value": _number_in_words_quetzales(
                                            invoice.grand_total
                                        ),
                                    },
                                ],
                            }
                        ]
                    },
                    "AditionalInfo": [
                        {
                            "Name": "VALIDAR_REFERENCIA_INTERNA",
                            "Data": None,
                            "Value": "NO_VALIDAR",
                        }
                    ],
                }
            ]
        },
    }
