const d = document.getElementById('drawer');

document.getElementById('menuBtn').onclick = () => {
  d.classList.add('open');
};

document.getElementById('closeMenu').onclick = e => {
  e.preventDefault();
  d.classList.remove('open');
};

const dlg = document.getElementById('leadDialog');

const openLead = () => {
  d.classList.remove('open');
  dlg.showModal();
};

document.getElementById('requestBtn').onclick = openLead;

document.getElementById('drawerRequest').onclick = e => {
  e.preventDefault();
  openLead();
};

document.getElementById('cancelLead').onclick = () => {
  dlg.close();
};

document.getElementById('leadForm').onsubmit = async e => {
  e.preventDefault();

  const form = e.target;
  const msg = document.getElementById('leadMsg');
  const submitButton = form.querySelector('button[type="submit"]');

  const riskAccepted =
    document.getElementById('riskDisclosureAccepted').checked;

  const privacyAccepted =
    document.getElementById('privacyConsentAccepted').checked;

  if (!riskAccepted || !privacyAccepted) {
    msg.textContent =
      'You must accept both the Risk Disclosure and Privacy Policy before submitting.';
    return;
  }

  const body = Object.fromEntries(
    new FormData(form).entries()
  );

  body.risk_disclosure_accepted = true;
  body.privacy_consent_accepted = true;
  body.request_source = 'PUBLIC_REQUEST_INFORMATION';

  msg.textContent = 'Submitting...';
  submitButton.disabled = true;

  try {
    const r = await fetch('/api/leads', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });

    const j = await r.json();

    if (!r.ok) {
      throw new Error(
        j.error || 'Unable to submit'
      );
    }

    const leadId = j.lead_id || '';

    form.reset();

    window.location.href =
      '/thank-you.html?ref=' + encodeURIComponent(leadId);

  } catch (err) {
    msg.textContent =
      'Unable to submit: ' + err.message;

    submitButton.disabled = false;
  }
};