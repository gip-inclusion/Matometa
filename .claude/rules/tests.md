pytest uniquement : pas de `unittest` (ni `TestCase`, ni imports depuis le package `unittest`). Pour les mocks, utiliser le fixture **`mocker`** de **pytest-mock** (`mocker.patch`, `mocker.MagicMock`, etc.), pas `unittest.mock`.

`@pytest.mark.parametrize` dès qu’un même comportement est vérifié avec des entrées différentes. Ne pas dupliquer des fonctions de test pour varier les entrées.

Préférer des **fonctions usine** définies dans le fichier de test (ou localement dans le test) aux fixtures qui ne font que construire des objets sans état partagé ni setup/teardown. La duplication de données initiales explicites est acceptable ; la duplication de logique paramétrable ne l’est pas.

Si un comportement mérite un exemple, l’écrire comme test. Les tests sont la documentation vivante.

Tests nécessitant credentials ou réseau : `@pytest.mark.integration` (exclus par `make test`).

Chaque modification de code doit avoir un test correspondant.
