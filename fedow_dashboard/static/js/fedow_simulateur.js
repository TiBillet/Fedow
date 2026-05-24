/**
 * Recette de fonte attendue + moyennes par portefeuille — 100% cote client.
 * / Expected melting revenue + per-wallet averages — 100% client-side.
 *
 * LOCALISATION : fedow_dashboard/static/js/fedow_simulateur.js
 *
 * Lit deux sources injectees par le template :
 *
 *  #data-monnaie-fondante (calcule en base, par carte) :
 *    wallets_dormants = [[age_jours, solde_centimes], ...]  (cartes user, solde > 0)
 *    depense_totale, currency_code, nb_vides, total_charge
 *
 *  #data-courbe-survie (fichier JSON pre-calcule, commande `courbe_survie`) :
 *    survie        = [{age_mois, part_restante}, ...]                 (S(age))
 *    stock_par_age = [{age_mois, montant_centimes, nb_cartes}, ...]   (stock actuel par age)
 *    Absente pour les monnaies sans courbe : on n'affiche alors pas la projection.
 *
 * GRAPHE « chart-devenir » : recette de fonte ATTENDUE dans le futur, mois par mois.
 * On projette l'argent DEJA sur les cartes : une tranche d'age `a` devient fondable
 * quand son age atteint le seuil, soit dans (seuil - a) mois. Le montant fondable est
 * ce qui en reste a ce moment-la (via la courbe de survie). On ne montre que la zone
 * CERTAINE [0, seuil] : aucune recharge future supposee, aucune speculation.
 * Deux series comparees : « tout d'un coup » et « 1 euro / mois » (etale).
 *
 * Le curseur seuil pilote la projection ET la comparaison actifs/inactifs des moyennes.
 * Tout est recalcule en direct, aucune requete, aucune ecriture.
 *
 * Depend de : Chart.js (charge avant ce fichier).
 */
document.addEventListener("DOMContentLoaded", function () {
    const balise = document.getElementById("data-monnaie-fondante");
    if (!balise || typeof Chart === "undefined") {
        return;
    }
    let donnees;
    try {
        donnees = JSON.parse(balise.textContent);
    } catch (e) {
        console.error("Devenir : JSON monnaie-fondante illisible", e);
        return;
    }

    const walletsDormants = donnees.wallets_dormants || [];   // [[age_jours, solde_centimes], ...]
    const devise = donnees.currency_code || "";
    const depenseTotale = donnees.depense_totale || 0;        // centimes

    // ---------- Courbe de survie + stock par age (peut etre absent) ----------
    // / Survival curve + stock per age (may be missing for non-FED currencies).
    let survieMap = [];     // survieMap[age_mois] = part_restante (0..1)
    let stockParAge = [];   // [{age_mois, montant_centimes, nb_cartes}, ...]
    const baliseSurvie = document.getElementById("data-courbe-survie");
    if (baliseSurvie) {
        try {
            const survieJson = JSON.parse(baliseSurvie.textContent) || {};
            (survieJson.survie || []).forEach(function (p) {
                survieMap[p.age_mois] = p.part_restante;
            });
            stockParAge = survieJson.stock_par_age || [];
        } catch (e) {
            console.error("Devenir : JSON courbe-survie illisible", e);
        }
    }
    // On peut projeter seulement si la courbe est presente.
    // / We can only project if the curve is present.
    const survieDispo = survieMap.length > 0 && stockParAge.length > 0;

    // S(age) : part restante a cet age, cappee a l'horizon de la courbe.
    // / S(age): remaining share at this age, capped at the curve horizon.
    function S(age) {
        if (!survieMap.length) return null;
        let idx = age;
        if (idx < 0) idx = 0;
        if (idx >= survieMap.length) idx = survieMap.length - 1;
        return survieMap[idx];
    }

    // ---------- Helpers ----------
    function formate(centimes) {
        return (centimes / 100).toLocaleString("fr-FR", {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        }) + " " + devise;
    }
    function mediane(valeurs) {
        if (!valeurs.length) return 0;
        const triees = valeurs.slice().sort(function (a, b) { return a - b; });
        const milieu = Math.floor(triees.length / 2);
        return triees.length % 2 ? triees[milieu] : (triees[milieu - 1] + triees[milieu]) / 2;
    }
    function texte(id, valeur) {
        const el = document.getElementById(id);
        if (el) el.textContent = valeur;
    }

    // ---------- Moyennes statiques (ne dependent pas du seuil) ----------
    const soldes = walletsDormants.map(function (w) { return w[1]; });
    const nbWallets = soldes.length;
    const soldeTotal = soldes.reduce(function (s, v) { return s + v; }, 0);

    const nbVides = donnees.nb_vides || 0;
    const nbCartesAsset = nbWallets + nbVides;  // détenteurs (>0) + vidées = cartes ayant utilisé l'asset
    if (nbWallets > 0) {
        texte("moy-nb-detenteurs", nbWallets.toLocaleString("fr-FR"));
        texte("moy-nb-vides", nbVides.toLocaleString("fr-FR"));
        texte("moy-nb-total", nbCartesAsset.toLocaleString("fr-FR"));
        // Dépense moyenne rapportée à toutes les cartes ayant utilisé l'asset.
        // / Average spend over all cards that used the asset.
        texte("moy-depense", formate(nbCartesAsset ? depenseTotale / nbCartesAsset : 0));
        // Solde moyen / médian sur les détenteurs ACTUELS (solde > 0).
        // / Average / median balance over CURRENT holders (balance > 0).
        texte("moy-solde", formate(soldeTotal / nbWallets));
        texte("moy-solde-median", formate(mediane(soldes)));
        // Solde moyen rapporté à TOUTES les cartes ayant utilisé l'asset (vidées incluses).
        // / Average balance over ALL cards that used the asset (emptied included).
        texte("moy-solde-carte", formate(nbCartesAsset ? soldeTotal / nbCartesAsset : 0));
    }

    // ---------- Breakage (rétention) : snapshot du solde sur cartes par ancienneté ----------
    // / Breakage (retention): snapshot of on-card balance by age since last activity.
    const totalCharge = donnees.total_charge || 0;
    if (nbWallets > 0) {
        // Tranches d'âge (jours) : <1 mois, 1-3, 3-6, 6-12, >12 mois.
        // / Age buckets (days): <1 month, 1-3, 3-6, 6-12, >12 months.
        const buckets = [0, 0, 0, 0, 0];
        for (let i = 0; i < walletsDormants.length; i++) {
            const age = walletsDormants[i][0];
            const val = walletsDormants[i][1];
            if (age < 30) buckets[0] += val;
            else if (age < 90) buckets[1] += val;
            else if (age < 180) buckets[2] += val;
            else if (age < 365) buckets[3] += val;
            else buckets[4] += val;
        }
        const pctCharge = function (centimes) {
            return totalCharge
                ? (centimes / totalCharge * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " %"
                : "—";
        };
        for (let b = 0; b < 5; b++) {
            texte("brk-b" + b + "-solde", formate(buckets[b]));
            texte("brk-b" + b + "-pct", pctCharge(buckets[b]));
        }
        texte("brk-taux", pctCharge(soldeTotal));
        texte("brk-restant", formate(soldeTotal));
        texte("brk-charge", formate(totalCharge));
    }

    // ---------- Controles ----------
    const champSeuil = document.getElementById("sim-seuil");
    const champMontant = document.getElementById("sim-montant");
    const champHorizon = document.getElementById("sim-horizon");
    const canvas = document.getElementById("chart-devenir");

    let graphique = null;

    // Recalcule la projection de recette ET les moyennes dynamiques selon les controles.
    // / Recompute the revenue projection AND the dynamic averages from the controls.
    function recalculer() {
        if (!champSeuil) {
            return; // Pas de simulateur sur cette page (etat vide).
        }
        const seuil = parseInt(champSeuil.value, 10);                       // mois
        const montantFixe = Math.round(parseFloat(champMontant.value || "0") * 100); // centimes/mois/carte
        const horizon = parseInt(champHorizon.value, 10);                   // mois affiches

        // ----- Recette de fonte ATTENDUE, mois par mois (zone certaine) -----
        // Pour chaque tranche d'age `a` du stock actuel :
        //   - elle devient fondable dans (seuil - a) mois (0 si deja au-dela),
        //   - le montant fondable = ce qui en reste a ce moment-la (survie conditionnelle).
        // / Expected melting revenue per month; each age tranche becomes fondable
        //   when its age reaches the threshold; amount = what survives until then.
        const barreTout = [];   // centimes : on recupere tout d'un coup
        const barreFixe = [];   // centimes : on preleve un montant fixe par mois
        for (let t = 0; t <= horizon; t++) { barreTout.push(0); barreFixe.push(0); }
        let cartesConcernees = 0;

        if (survieDispo && montantFixe >= 0) {
            const survieSeuil = S(seuil);
            for (let i = 0; i < stockParAge.length; i++) {
                const age = stockParAge[i].age_mois;
                const montant = stockParAge[i].montant_centimes;
                const cartes = stockParAge[i].nb_cartes || 0;

                let partRestante;   // part encore presente quand l'age atteint le seuil
                let moisFonte;      // dans combien de mois la tranche devient fondable
                if (age >= seuil) {
                    partRestante = 1;       // deja au-dela du seuil : fondable maintenant
                    moisFonte = 0;
                } else {
                    const survieAge = S(age);
                    partRestante = (survieAge && survieAge > 0) ? (survieSeuil / survieAge) : 0;
                    moisFonte = seuil - age;
                }
                if (partRestante > 1) partRestante = 1;   // garde-fou

                const fondMontant = montant * partRestante;
                const fondCartes = cartes * partRestante;
                cartesConcernees += fondCartes;

                // Mode « tout d'un coup » : tout au mois de fondabilite.
                if (moisFonte <= horizon) {
                    barreTout[moisFonte] += fondMontant;
                }

                // Mode « 1 euro / mois » : on etale a partir du mois de fondabilite,
                // au rythme de (cartes x montant fixe) par mois, jusqu'a epuisement.
                let reste = fondMontant;
                const rythme = fondCartes * montantFixe;   // centimes / mois
                let t = moisFonte;
                while (reste > 0.5 && t <= horizon) {
                    const pris = (rythme > 0 && rythme < reste) ? rythme : reste;
                    barreFixe[t] += pris;
                    reste -= pris;
                    if (rythme <= 0) break;   // montant fixe nul : pas d'etalement possible
                    t++;
                }
            }
        }

        // Series + labels (centimes -> unite).
        const labels = [];
        const dataTout = [];
        const dataFixe = [];
        for (let t = 0; t <= horizon; t++) {
            labels.push(t === 0 ? "Auj." : "M+" + t);
            dataTout.push(barreTout[t] / 100);
            dataFixe.push(barreFixe[t] / 100);
        }

        // KPI
        const totalTout = barreTout.reduce(function (s, v) { return s + v; }, 0);
        const totalFixe = barreFixe.reduce(function (s, v) { return s + v; }, 0);
        texte("dev-total-tout", formate(totalTout));
        texte("dev-total-fixe", formate(totalFixe));
        texte("dev-deja", formate(barreTout[0]));
        texte("dev-cartes", Math.round(cartesConcernees).toLocaleString("fr-FR"));

        // Graphe en barres groupees : « tout d'un coup » vs « 1 euro / mois ».
        if (canvas) {
            if (graphique) {
                graphique.data.labels = labels;
                graphique.data.datasets[0].data = dataTout;
                graphique.data.datasets[1].data = dataFixe;
                graphique.update();
            } else {
                graphique = new Chart(canvas, {
                    type: "bar",
                    data: {
                        labels: labels,
                        datasets: [
                            {
                                label: "Tout d'un coup (" + devise + ")",
                                data: dataTout,
                                backgroundColor: "#fb6340",
                            },
                            {
                                label: "1 € / mois (" + devise + ")",
                                data: dataFixe,
                                backgroundColor: "#5e72e4",
                            },
                        ],
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: true } },
                        scales: {
                            x: { grid: { color: "rgba(128,128,128,0.15)" } },
                            y: { grid: { color: "rgba(128,128,128,0.15)" }, beginAtZero: true },
                        },
                    },
                });
            }
        }

        // ----- Moyennes dynamiques : actifs / inactifs selon le seuil -----
        // / Dynamic averages: active vs inactive split by the threshold.
        const seuilJours = seuil * 30;
        const inactifs = [];
        const actifs = [];
        let volumeInactif = 0;
        for (let i = 0; i < walletsDormants.length; i++) {
            const age = walletsDormants[i][0];
            const solde = walletsDormants[i][1];
            if (age >= seuilJours) { inactifs.push(solde); volumeInactif += solde; }
            else { actifs.push(solde); }
        }
        const soldeActifs = actifs.reduce(function (s, v) { return s + v; }, 0);
        texte("moy-seuil", String(seuil));
        texte("moy-nb-actifs", actifs.length.toLocaleString("fr-FR"));
        texte("moy-actifs", actifs.length ? formate(soldeActifs / actifs.length) : "—");
        texte("moy-actifs-median", actifs.length ? formate(mediane(actifs)) : "—");
        texte("moy-nb-inactifs", inactifs.length.toLocaleString("fr-FR"));
        texte("moy-inactifs", inactifs.length ? formate(volumeInactif / inactifs.length) : "—");
        texte("moy-inactifs-median", inactifs.length ? formate(mediane(inactifs)) : "—");
        const pctDormant = soldeTotal ? (volumeInactif / soldeTotal * 100) : 0;
        texte("moy-pct-dormant", pctDormant.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " %");
    }

    function majLibelles() {
        if (champSeuil) texte("sim-seuil-val", champSeuil.value);
        if (champHorizon) texte("sim-horizon-val", champHorizon.value);
    }

    // ---------- Ecouteurs ----------
    [champSeuil, champMontant, champHorizon].forEach(function (el) {
        if (el) el.addEventListener("input", function () { majLibelles(); recalculer(); });
    });

    // ---------- Premier rendu ----------
    majLibelles();
    recalculer();
});
