/**
 * Dessine les graphiques du tableau de bord d'un asset Fedow.
 * / Draws the Fedow asset dashboard charts.
 *
 * LOCALISATION : fedow_dashboard/static/js/fedow_charts.js
 *
 * Les donnees sont calculees cote serveur (Python, en cache) puis injectees dans
 * la page via deux balises json_script. Ici, le JS ne fait QUE dessiner : aucune
 * logique metier cote client.
 * / Data is computed server-side (cached) and injected via two json_script tags.
 *   This JS only draws the charts — no business logic on the client.
 *
 * COMMUNICATION :
 * Lit  : #data-monnaie-fondante et #data-temporel (json_script rendus par le template)
 * Depend de : Chart.js (chart.umd.4.4.1.min.js, charge AVANT ce fichier)
 */
document.addEventListener("DOMContentLoaded", function () {
    // Si Chart.js n'est pas charge, on ne fait rien (page sans graphique).
    // / If Chart.js is not loaded, do nothing (page without charts).
    if (typeof Chart === "undefined") {
        return;
    }

    // Couleurs lisibles en theme clair ET sombre (gris moyen + grille discrete).
    // / Colors readable in both light and dark themes (mid gray + subtle grid).
    const couleurTexte = "#8898aa";
    const couleurGrille = "rgba(128, 128, 128, 0.15)";

    Chart.defaults.color = couleurTexte;
    Chart.defaults.font.family = "inherit";

    /**
     * Lit un json_script et renvoie l'objet, ou null si absent/illisible.
     * / Reads a json_script tag and returns the object, or null if missing/unreadable.
     */
    function lireDonnees(idBalise) {
        const balise = document.getElementById(idBalise);
        if (!balise) {
            return null;
        }
        try {
            return JSON.parse(balise.textContent);
        } catch (erreur) {
            console.error("Fedow charts : JSON illisible pour #" + idBalise, erreur);
            return null;
        }
    }

    // --- Graphe 1 : Monnaie fondante (courbe cumulee) ---
    // Montre combien de tokens dorment sur les wallets inactifs, par seuil.
    // / Chart 1: melting money (cumulative line) — dormant tokens per inactivity threshold.
    const donneesFondante = lireDonnees("data-monnaie-fondante");
    const canvasFondante = document.getElementById("chart-monnaie-fondante");
    if (donneesFondante && canvasFondante) {
        new Chart(canvasFondante, {
            type: "line",
            data: {
                labels: donneesFondante.labels,
                datasets: [{
                    label: "Tokens dormants (" + donneesFondante.currency_code + ")",
                    data: donneesFondante.data,
                    borderColor: "#fb6340",
                    backgroundColor: "rgba(251, 99, 64, 0.18)",
                    fill: true,
                    tension: 0.3,
                    pointRadius: 4,
                    pointBackgroundColor: "#fb6340",
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: true },
                    tooltip: {
                        callbacks: {
                            // Affiche la valeur exacte au survol.
                            // / Show the exact value on hover.
                            label: function (contexte) {
                                return contexte.parsed.y + " " + donneesFondante.currency_code;
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { color: couleurGrille },
                        title: { display: true, text: "Inactif depuis au moins…" },
                    },
                    y: {
                        grid: { color: couleurGrille },
                        beginAtZero: true,
                    },
                },
            },
        });
    }

    // --- Graphe 2 : Transactions dans le temps (barres empilees par action) ---
    // Montre le volume par mois, ventile par type d'action (creation, vente, etc.).
    // / Chart 2: transactions over time (stacked bars per action).
    const donneesTemporel = lireDonnees("data-temporel");
    const canvasTemporel = document.getElementById("chart-temporel");
    if (donneesTemporel && canvasTemporel) {
        new Chart(canvasTemporel, {
            type: "bar",
            data: {
                labels: donneesTemporel.labels,
                datasets: donneesTemporel.datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: true } },
                scales: {
                    x: { stacked: true, grid: { color: couleurGrille } },
                    y: { stacked: true, grid: { color: couleurGrille }, beginAtZero: true },
                },
            },
        });
    }

    // --- Graphe 3 : Pouls du reseau (nombre de transactions par mois) ---
    // Page d'accueil reseau uniquement ; ignore sur les pages asset (canvas absent).
    // / Chart 3: network pulse (transaction count per month). Home page only.
    const donneesPouls = lireDonnees("data-pouls-reseau");
    const canvasPouls = document.getElementById("chart-volume-reseau");
    if (donneesPouls && canvasPouls) {
        new Chart(canvasPouls, {
            type: "bar",
            data: {
                labels: donneesPouls.labels,
                datasets: [{
                    label: "Transactions",
                    data: donneesPouls.data,
                    backgroundColor: "#5e72e4",
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: couleurGrille } },
                    y: { grid: { color: couleurGrille }, beginAtZero: true, ticks: { precision: 0 } },
                },
            },
        });
    }
});
