from xml.etree import ElementTree as ET

from kingo_fel.services.nuc_json import build_fact_nuc_json


def _text(parent, tag, value):
    element = ET.SubElement(parent, tag)
    element.text = str(value)
    return element


def _info_list(parent, tag, values):
    container = ET.SubElement(parent, tag)

    for value in values:
        info = ET.SubElement(container, "Info")

        for attribute in ("Name", "Data", "Value"):
            content = value.get(attribute)

            if content is not None:
                info.set(attribute, str(content))

    return container


def _address(parent, address):
    container = ET.SubElement(parent, "AddressInfo")

    for tag in ("Address", "City", "District", "State", "Country"):
        _text(container, tag, address[tag])

    return container


def _transaction(parent, tag, transaction):
    container = ET.SubElement(parent, tag)

    for field in (
        "Code",
        "Description",
        "TaxableAmount",
        "ChargableAmount",
        "Rate",
        "Amount",
    ):
        if transaction.get(field) is not None:
            _text(container, field, transaction[field])

    return container


def _item(parent, item):
    element = ET.SubElement(parent, "Item")

    _text(element, "Type", item["Type"])
    _text(element, "Description", item["Description"])
    _text(element, "Qty", item["Qty"])
    _text(element, "UnitOfMeasure", item["UnitOfMeasure"])
    _text(element, "Price", item["Price"])

    if item.get("Discounts"):
        discounts = ET.SubElement(element, "Discounts")

        for discount in item["Discounts"]["Discount"]:
            _transaction(discounts, "Discount", discount)

    taxes = ET.SubElement(element, "Taxes")

    for tax in item["Taxes"]["Tax"]:
        _transaction(taxes, "Tax", tax)

    totals = ET.SubElement(element, "Totals")
    _text(totals, "TotalItem", item["Totals"]["TotalItem"])

    return element


def build_fact_nuc_xml(invoice, settings):
    nuc = build_fact_nuc_json(invoice, settings)

    root = ET.Element("Root")

    _text(root, "Version", nuc["Version"])
    _text(root, "CountryCode", nuc["CountryCode"])

    header = ET.SubElement(root, "Header")
    _text(header, "DocType", nuc["Header"]["DocType"])
    _text(header, "IssuedDateTime", nuc["Header"]["IssuedDateTime"])
    _text(header, "Currency", nuc["Header"]["Currency"])

    seller_data = nuc["Seller"]
    seller = ET.SubElement(root, "Seller")
    _text(seller, "TaxID", seller_data["TaxID"])
    _info_list(
        seller,
        "TaxIDAdditionalInfo",
        seller_data["TaxIDAdditionalInfo"],
    )
    _text(seller, "Name", seller_data["Name"])
    _info_list(seller, "AdditionlInfo", seller_data["AdditionlInfo"])

    branch = ET.SubElement(seller, "BranchInfo")
    _text(branch, "Code", seller_data["BranchInfo"]["Code"])
    _text(branch, "Name", seller_data["BranchInfo"]["Name"])
    _address(branch, seller_data["BranchInfo"]["AddressInfo"])

    buyer_data = nuc["Buyer"]
    buyer = ET.SubElement(root, "Buyer")
    _text(buyer, "TaxID", buyer_data["TaxID"])

    if buyer_data.get("TaxIDType"):
        _text(buyer, "TaxIDType", buyer_data["TaxIDType"])

    _text(buyer, "Name", buyer_data["Name"])

    items = ET.SubElement(root, "Items")

    for item in nuc["Items"]:
        _item(items, item)

    totals_data = nuc["Totals"]
    totals = ET.SubElement(root, "Totals")

    total_taxes = ET.SubElement(totals, "TotalTaxes")

    for tax in totals_data["TotalTaxes"]["TotalTax"]:
        _transaction(total_taxes, "TotalTax", tax)

    grand_total = ET.SubElement(totals, "GrandTotal")
    _text(grand_total, "InvoiceTotal", totals_data["GrandTotal"]["InvoiceTotal"])

    additional_document_info = ET.SubElement(root, "AdditionalDocumentInfo")

    for info_data in nuc["AdditionalDocumentInfo"]["AdditionalInfo"]:
        additional_info = ET.SubElement(
            additional_document_info,
            "AdditionalInfo",
        )
        _text(additional_info, "Code", info_data["Code"])
        _text(additional_info, "Type", info_data["Type"])

    return ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=True,
    ).decode("utf-8")