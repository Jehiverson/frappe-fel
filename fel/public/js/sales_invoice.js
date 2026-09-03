function emit_fel_invoice(frm) {
    frappe.confirm(
        __(
            "Se emitirá y certificará esta factura ante Digifact y SAT. " +
                "Después no podrá editarse. ¿Deseas continuar?"
        ),
        () => {
            frappe.call({
                method: "kingo_fel.api.fel.prepare_fel_document",
                args: {
                    sales_invoice_name: frm.doc.name,
                },
                freeze: true,
                freeze_message: __("Preparando documento FEL..."),
                callback(prepareResponse) {
                    const prepared = prepareResponse.message;

                    if (!prepared || !prepared.success) {
                        return;
                    }

                    frappe.call({
                        method: "kingo_fel.api.fel.certify_fel_document",
                        args: {
                            fel_document_name: prepared.fel_document_id,
                        },
                        freeze: true,
                        freeze_message: __("Certificando factura ante Digifact..."),
                        callback(certifyResponse) {
                            const result = certifyResponse.message;

                            if (!result) {
                                return;
                            }

                            if (!result.success) {
                                frappe.msgprint({
                                    title: __("No se pudo certificar FEL"),
                                    indicator: "red",
                                    message: result.message,
                                });
                                return;
                            }

                            frappe.show_alert({
                                message: __(
                                    "Factura FEL certificada. Serie: {0}, número: {1}",
                                    [result.fel_series, result.fel_number]
                                ),
                                indicator: "green",
                            });

                            // Mantiene al usuario en esta misma factura,
                            // ya enviada y sin posibilidad de edición.
                            frm.reload_doc();
                        },
                    });
                },
            });
        }
    );
}

frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        // Solo para facturas guardadas que siguen en borrador.
        if (frm.is_new() || frm.doc.docstatus !== 0) {
            return;
        }

        frm.add_custom_button(
            __("Emitir factura FEL"),
            () => emit_fel_invoice(frm),
            __("FEL")
        );
    },
});