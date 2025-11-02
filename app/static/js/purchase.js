document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('purchaseForm');
    const invoiceNumberInput = document.getElementById('invoice_number');

    async function checkInvoiceNumber() {
        const invoiceNumber = invoiceNumberInput.value.trim();
        if (!invoiceNumber) {
            alert('Nomor faktur harus diisi!');
            return false;
        }

        try {
            const response = await fetch(`/api/check_invoice_number?invoice_number=${encodeURIComponent(invoiceNumber)}`);
            const data = await response.json();
            if (data.exists) {
                alert('Nomor faktur sudah digunakan. Silakan gunakan yang lain.');
                return false;
            }
            return true;
        } catch (error) {
            console.error('Error checking invoice number:', error);
            return false;
        }
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const isValidInvoice = await checkInvoiceNumber();
        if (!isValidInvoice) {
            return;
        }

        const formData = new FormData(form);
        const json = JSON.stringify(Object.fromEntries(formData.entries()));

        fetch(form.action, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: json
        }).then(response => {
            if (!response.ok) throw new Error('Network response was not ok.');
            return response.json();
        }).then(data => {
            console.log('Success:', data);
            alert('Data berhasil disimpan!');
            window.location.reload();
        }).catch(error => {
            console.error('Error:', error);
            alert('Gagal menyimpan data: ' + error.message);
        });
    });
});
