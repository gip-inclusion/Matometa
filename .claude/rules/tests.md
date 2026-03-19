pytest uniquement. Pas de unittest, pas de doctest.

Utiliser `@pytest.mark.parametrize` systématiquement quand un test vérifie le même comportement avec des entrées différentes. Ne pas dupliquer des fonctions de test pour varier les entrées.

Si un comportement mérite un exemple, l'écrire comme test. Les tests sont la documentation vivante.

Tests nécessitant credentials ou réseau : `@pytest.mark.integration` (exclus par `make test`).

Chaque modification de code doit avoir un test correspondant.
