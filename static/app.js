// Small progressive enhancements. The app works without JavaScript.
(function () {
    'use strict';

    // Ask before destructive actions: <form data-confirm="Are you sure?">
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        form.addEventListener('submit', function (event) {
            if (!window.confirm(form.dataset.confirm)) {
                event.preventDefault();
            }
        });
    });

    // Highlight the chosen option card and update the progress counter on the quiz page.
    var quizForm = document.getElementById('quiz-form');
    if (quizForm) {
        var progress = document.getElementById('quiz-progress');
        var total = quizForm.querySelectorAll('input[name="question_id"]').length;

        var refresh = function () {
            quizForm.querySelectorAll('.option-card').forEach(function (card) {
                var input = card.querySelector('input[type="radio"]');
                card.classList.toggle('selected', input.checked);
            });
            if (progress) {
                var answered = new Set();
                quizForm.querySelectorAll('input[type="radio"]:checked').forEach(function (r) {
                    answered.add(r.name);
                });
                progress.textContent = answered.size + ' / ' + total + ' answered';
            }
        };

        quizForm.addEventListener('change', refresh);
        // Clicking anywhere on the card selects its option.
        quizForm.querySelectorAll('.option-card').forEach(function (card) {
            card.addEventListener('click', function (event) {
                var input = card.querySelector('input[type="radio"]');
                if (event.target !== input && event.target.tagName !== 'LABEL') {
                    input.checked = true;
                    refresh();
                }
            });
        });
        refresh();
    }

    // Open the dashboard tab named in the URL hash (e.g. /admin/dashboard#questions).
    if (window.location.hash && window.bootstrap) {
        var trigger = document.querySelector('[data-bs-target="' + window.location.hash + '"]');
        if (trigger) {
            window.bootstrap.Tab.getOrCreateInstance(trigger).show();
        }
    }
    document.querySelectorAll('#dashboardTabs [data-bs-toggle="tab"]').forEach(function (tab) {
        tab.addEventListener('shown.bs.tab', function () {
            history.replaceState(null, '', tab.dataset.bsTarget);
        });
    });
})();
