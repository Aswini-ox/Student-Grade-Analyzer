(() => {
  const openButton = document.querySelector('[data-sidebar-open]');
  const setSidebar = (open) => {
    document.body.classList.toggle('sidebar-open', open);
    if (openButton) openButton.setAttribute('aria-expanded', String(open));
  };
  openButton?.addEventListener('click', () => setSidebar(!document.body.classList.contains('sidebar-open')));
  document.querySelector('[data-sidebar-close]')?.addEventListener('click', () => setSidebar(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
      setSidebar(false);
      openButton?.focus();
    }
  });
  document.querySelectorAll('[data-dismiss-alert]').forEach((button) => button.addEventListener('click', () => button.closest('.flash')?.remove()));
  document.querySelectorAll('form[data-confirm]').forEach((form) => form.addEventListener('submit', (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  const form = document.querySelector('[data-student-form]');
  if (form) {
    const marks = [...form.querySelectorAll('[data-mark]')];
    const preview = form.querySelector('[data-average-preview]');
    const updatePreview = () => {
      const valid = marks.every((input) => input.value.trim() !== '' && input.validity.valid && Number.isFinite(Number(input.value)));
      if (preview) preview.textContent = valid ? `${(marks.reduce((sum, input) => sum + Number(input.value), 0) / marks.length).toFixed(1)}%` : '—';
    };
    marks.forEach((input) => input.addEventListener('input', updatePreview));
    updatePreview();
  }
  const readData = (id) => {
    const element = document.getElementById(id);
    if (!element) return null;
    try { return JSON.parse(element.textContent); } catch { return null; }
  };
  const colors = ['#5476e5', '#819bf2', '#a8b9f4', '#79c6b3', '#f2c379', '#eaa2aa'];
  const gradeCanvas = document.getElementById('grade-chart');
  const gradeData = readData('grade-data');
  const subjectCanvas = document.getElementById('subject-chart');
  const subjectData = readData('subject-data');
  if (typeof window.Chart !== 'function') {
    if (gradeCanvas) {
      gradeCanvas.hidden = true;
      const center = gradeCanvas.parentElement.querySelector('.chart-center');
      if (center) center.innerHTML = '<span>CHART UNAVAILABLE</span>';
    }
    if (subjectCanvas) {
      subjectCanvas.parentElement.hidden = true;
      const fallback = document.querySelector('[data-chart-fallback="subject-chart"]');
      if (fallback) fallback.hidden = false;
    }
    return;
  }
  if (gradeCanvas && gradeData) {
    const labels = ['A+', 'A', 'B', 'C', 'D', 'F'];
    new Chart(gradeCanvas, {type: 'doughnut', data: {labels, datasets: [{data: labels.map((label) => Number(gradeData[label] || 0)), backgroundColor: colors, borderWidth: 0, spacing: 3, borderRadius: 3}]}, options: {responsive: true, maintainAspectRatio: false, cutout: '77%', plugins: {legend: {display: false}, tooltip: {enabled: true}}}});
  }
  if (subjectCanvas && subjectData) {
    const labels = Object.keys(subjectData);
    new Chart(subjectCanvas, {type: 'bar', data: {labels, datasets: [{label: 'Average score', data: labels.map((label) => Number(subjectData[label] || 0)), backgroundColor: '#8ca5f3', hoverBackgroundColor: '#5476e5', borderRadius: 7, maxBarThickness: 38}]}, options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {display: false}}, scales: {y: {beginAtZero: true, max: 100, grid: {color: '#f0f3f8'}, border: {display: false}, ticks: {color: '#a4afbf', font: {size: 10}, callback: (value) => `${value}%`}}, x: {grid: {display: false}, border: {display: false}, ticks: {color: '#8f9caf', font: {size: 10}}}}}});
  }
})();
