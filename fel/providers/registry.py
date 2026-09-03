import frappe

from fel.providers.digifact import DigifactProvider


PROVIDER_CLASSES = {
    "digifact": DigifactProvider,
}


def get_provider(company_settings):
    """Devuelve el adaptador configurado para una compañía."""

    provider_code = company_settings.fel_provider

    provider_class = PROVIDER_CLASSES.get(provider_code)

    if not provider_class:
        frappe.throw(
            f"No existe un adaptador FEL instalado para el proveedor '{provider_code}'."
        )

    return provider_class(company_settings)