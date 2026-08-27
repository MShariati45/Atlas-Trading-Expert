const params = new URLSearchParams(window.location.search);
const ref = params.get('ref');

if (ref) {
  const referenceBox = document.getElementById('leadReference');
  const referenceValue = document.getElementById('leadReferenceValue');

  referenceValue.textContent = ref;
  referenceBox.style.display = 'block';
}