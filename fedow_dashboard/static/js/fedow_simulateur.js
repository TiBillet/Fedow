/**
 * Recette de fonte attendue (nette des frais Stripe) + bilan + moyennes — 100% client.
 * / Expected melting revenue (net of Stripe fees) + balance + averages — 100% client-side.
 *
 * LOCALISATION : fedow_dashboard/static/js/fedow_simulateur.js
 *
 * Sources injectees par le template :
 *  #data-monnaie-fondante : wallets_dormants, depense_totale, currency_code, nb_vides, total_charge.
 *  #data-courbe-survie    : survie [{age_mois, part_restante}],
 *                           stock_par_age [{age_mois, montant_centimes, nb_cartes}],
 *                           refill_par_age [{age_mois, montant_centimes}] (recharge totale par age),
 *                           total_refill_centimes.
 *
 * FRAIS STRIPE : payes A LA RECHARGE (0,25 + 1,6% selon canal), pas a la fonte. On les
 * recalcule au taux effectif saisi (defaut 2%, modifiable a l'ecran), sur la TOTALITE
 * du rechargé. La fonte sert a rembourser ces frais → recette NETTE = fonte − frais.
 *
 * GRAPHE « chart-devenir » (zone certaine [0, seuil]) : barres = recette de fonte NETTE
 * par mois (cohorte rechargee a `mois − seuil`), 2 modes (tout d'un coup / 1 €/mois) ;
 * ligne rouge = frais Stripe de la cohorte. BILAN : rechargé / frais / dormant / net.
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

    const walletsDormants = donnees.wallets_dormants || [];
    const devise = donnees.currency_code || "";
    const depenseTotale = donnees.depense_totale || 0;

    // ---------- Courbe de survie + stock + recharge par age (peut etre absent) ----------
    let survieMap = [];        // survieMap[age] = part_restante
    let stockParAge = [];      // [{age_mois, montant_centimes, nb_cartes}]
    let refillMap = {};        // refillMap[age] = montant recharge total a cet age (centimes)
    let totalRefill = 0;       // recharge totale (centimes)
    let stockTotal = 0;        // dormant total sur les cartes (centimes)
    const baliseSurvie = document.getElementById("data-courbe-survie");
    if (baliseSurvie) {
        try {
            const sj = JSON.parse(baliseSurvie.textContent) || {};
            (sj.survie || []).forEach(function (p) { survieMap[p.age_mois] = p.part_restante; });
            stockParAge = sj.stock_par_age || [];
            (sj.refill_par_age || []).forEach(function (r) { refillMap[r.age_mois] = r.montant_centimes; });
            totalRefill = sj.total_refill_centimes || 0;
            stockTotal = stockParAge.reduce(function (s, x) { return s + x.montant_centimes; }, 0);
        } catch (e) {
            console.error("Devenir : JSON courbe-survie illisible", e);
        }
    }
    const survieDispo = survieMap.length > 0 && stockParAge.length > 0;

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
    const nbCartesAsset = nbWallets + nbVides;
    if (nbWallets > 0) {
        texte("moy-nb-detenteurs", nbWallets.toLocaleString("fr-FR"));
        texte("moy-nb-vides", nbVides.toLocaleString("fr-FR"));
        texte("moy-nb-total", nbCartesAsset.toLocaleString("fr-FR"));
        texte("moy-depense", formate(nbCartesAsset ? depenseTotale / nbCartesAsset : 0));
        texte("moy-solde", formate(soldeTotal / nbWallets));
        texte("moy-solde-median", formate(mediane(soldes)));
        texte("moy-solde-carte", formate(nbCartesAsset ? soldeTotal / nbCartesAsset : 0));
    }

    // ---------- Breakage (rétention) : snapshot du solde sur cartes par ancienneté ----------
    const totalCharge = donnees.total_charge || 0;
    if (nbWallets > 0) {
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
    const champFrais = document.getElementById("sim-frais");
    const canvas = document.getElementById("chart-devenir");

    let graphique = null;

    function recalculer() {
        if (!champSeuil) {
            return;
        }
        const seuil = parseInt(champSeuil.value, 10);
        const montantFixe = Math.round(parseFloat(champMontant.value || "0") * 100); // centimes/mois/carte
        const horizon = parseInt(champHorizon.value, 10);
        const taux = parseFloat(champFrais.value || "0") / 100;                       // ex 0.02

        // ---------- Recette de fonte NETTE, mois par mois (zone certaine) ----------
        // Barre nette = fonte de la cohorte − frais Stripe de la cohorte (sur tout son rechargé).
        // / Net bar = cohort melting − the cohort's Stripe fees (on its whole recharge).
        const netTout = [];     // mode « tout d'un coup »
        const netFixe = [];     // mode « 1 €/mois »
        const fraisBar = [];    // ligne rouge : frais Stripe de la cohorte du mois
        for (let t = 0; t <= horizon; t++) { netTout.push(0); netFixe.push(0); fraisBar.push(0); }
        let fonteBrute = 0, fraisProjetes = 0, cartesConcernees = 0;

        if (survieDispo) {
            const survieSeuil = S(seuil);
            // Stock dormant REEL par age (pour les cohortes deja au-dela du seuil).
            // / Real dormant stock per age (for cohorts already past the threshold).
            const stockMap = {}, cartesMap = {};
            stockParAge.forEach(function (s) {
                stockMap[s.age_mois] = s.montant_centimes;
                cartesMap[s.age_mois] = s.nb_cartes || 0;
            });
            const soldeMoyenDormant = nbWallets > 0 ? (soldeTotal / nbWallets) : 0;

            // On parcourt chaque COHORTE de recharge (par age). La fonte d'une cohorte
            // se calcule sur sa RECHARGE (pas sur le stock residuel) :
            //   - age < seuil : recharge × survie(seuil) = ce qui dormira encore au seuil ;
            //   - age >= seuil : dormant REEL observe aujourd'hui (deja au-dela du seuil).
            // / Melting per recharge cohort: recharge × survival(threshold), or real stock if older.
            Object.keys(refillMap).forEach(function (cle) {
                const age = parseInt(cle, 10);
                const refillCohorte = refillMap[age];

                let fondMontant, fondCartes, moisFonte;
                if (age >= seuil) {
                    fondMontant = stockMap[age] || 0;
                    fondCartes = cartesMap[age] || 0;
                    moisFonte = 0;
                } else {
                    fondMontant = refillCohorte * survieSeuil;
                    fondCartes = soldeMoyenDormant > 0 ? (fondMontant / soldeMoyenDormant) : 0;
                    moisFonte = seuil - age;
                }

                const fraisCohorte = refillCohorte * taux;     // frais sur TOUT le rechargé de la cohorte
                const netCohorte = fondMontant - fraisCohorte;
                const ratioNet = fondMontant > 0 ? (netCohorte / fondMontant) : 0;

                fonteBrute += fondMontant;
                fraisProjetes += fraisCohorte;
                cartesConcernees += fondCartes;

                // Mode « tout d'un coup » : net au mois de fondabilite ; frais sur la ligne rouge.
                if (moisFonte <= horizon) {
                    netTout[moisFonte] += netCohorte;
                    fraisBar[moisFonte] += fraisCohorte;
                }

                // Mode « 1 €/mois » : on etale la fonte ; le net suit le meme ratio.
                let reste = fondMontant;
                const rythme = fondCartes * montantFixe;
                let t = moisFonte;
                while (reste > 0.5 && t <= horizon) {
                    const pris = (rythme > 0 && rythme < reste) ? rythme : reste;
                    netFixe[t] += pris * ratioNet;
                    reste -= pris;
                    if (rythme <= 0) break;
                    t++;
                }
            });
        }

        // ---------- BILAN : fonte (au seuil) − frais sur TOUT le rechargé ----------
        // / Balance: melting (at the threshold) − fees on the WHOLE recharged amount.
        const fraisTotaux = Math.round(totalRefill * taux);
        const recupNet = fonteBrute - fraisTotaux;
        texte("bil-recharge", formate(totalRefill));
        texte("bil-frais", formate(fraisTotaux));
        texte("bil-dormant", formate(fonteBrute));
        texte("bil-net", formate(recupNet));
        texte("bil-couverture", fraisTotaux > 0
            ? Math.round(fonteBrute / fraisTotaux * 100).toLocaleString("fr-FR") + " %"
            : "—");

        // Series + labels (centimes -> unite).
        const labels = [];
        const dataTout = [], dataFixe = [], dataFrais = [];
        for (let t = 0; t <= horizon; t++) {
            labels.push(t === 0 ? "Auj." : "M+" + t);
            dataTout.push(netTout[t] / 100);
            dataFixe.push(netFixe[t] / 100);
            dataFrais.push(fraisBar[t] / 100);
        }

        // KPI de la carte recette
        const totalNetTout = netTout.reduce(function (s, v) { return s + v; }, 0);
        const totalNetFixe = netFixe.reduce(function (s, v) { return s + v; }, 0);
        texte("dev-total-tout", formate(totalNetTout));
        texte("dev-total-fixe", formate(totalNetFixe));
        texte("dev-frais", formate(fraisProjetes));
        texte("dev-cartes", Math.round(cartesConcernees).toLocaleString("fr-FR"));

        // Graphe : barres nettes (2 modes) + ligne rouge des frais.
        if (canvas) {
            if (graphique) {
                graphique.data.labels = labels;
                graphique.data.datasets[0].data = dataTout;
                graphique.data.datasets[1].data = dataFixe;
                graphique.data.datasets[2].data = dataFrais;
                graphique.update();
            } else {
                graphique = new Chart(canvas, {
                    type: "bar",
                    data: {
                        labels: labels,
                        datasets: [
                            { type: "bar", label: "Net — tout d'un coup (" + devise + ")", data: dataTout, backgroundColor: "#fb6340" },
                            { type: "bar", label: "Net — 1 €/mois (" + devise + ")", data: dataFixe, backgroundColor: "#5e72e4" },
                            {
                                type: "line", label: "Frais Stripe (" + devise + ")", data: dataFrais,
                                borderColor: "#f5365c", backgroundColor: "transparent",
                                borderDash: [4, 4], pointRadius: 0, borderWidth: 2,
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
    [champSeuil, champMontant, champHorizon, champFrais].forEach(function (el) {
        if (el) el.addEventListener("input", function () { majLibelles(); recalculer(); });
    });

    // ---------- Premier rendu ----------
    majLibelles();
    recalculer();
});
