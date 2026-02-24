# Tag Manager API Reference

> Source: [Matomo Reporting API — TagManager module](https://developer.matomo.org/api-reference/reporting-api#TagManager)
> Scraped: 2026-02-27

API for plugin Tag Manager. Lets you configure all your containers, create, update
and delete tags, triggers, and variables. Create and publish new releases, enable
and disable preview/debug mode, and much more.

**Key concept:** A container may have several versions. The current version that a
user is editing is called the "draft" version. You can get the ID of the "draft"
version by calling `TagManager.getContainer`.

**Safety model:** All write operations (add/update/delete tags, triggers, variables)
modify the **draft version only**. Nothing goes live until `publishContainerVersion`
is explicitly called with a target environment.

## Methods Overview

| Category | Read | Write |
|----------|------|-------|
| Contexts & metadata | 8 | 0 |
| Containers | 3 | 4 |
| Tags | 2 | 5 |
| Triggers | 3 | 3 |
| Variables | 4 | 3 |
| Versions | 2 | 4 |
| Preview/debug | 0 | 3 |
| Import/export | 1 | 1 |
| **Total** | **23** | **23** |

## Contexts & Metadata (read-only)

```
TagManager.getAvailableContexts ()
TagManager.getAvailableEnvironments ()
TagManager.getAvailableEnvironmentsWithPublishCapability (idSite)
TagManager.getAvailableTagFireLimits ()
TagManager.getAvailableComparisons ()
TagManager.getAvailableTagTypesInContext (idContext)
TagManager.getAvailableTriggerTypesInContext (idContext)
TagManager.getAvailableVariableTypesInContext (idContext)
```

## Containers

```
# Read
TagManager.getContainers (idSite)
TagManager.getContainer (idSite, idContainer)
TagManager.getContainerEmbedCode (idSite, idContainer, environment)
TagManager.getContainerInstallInstructions (idSite, idContainer, environment, jsFramework = '')

# Write
TagManager.createDefaultContainerForSite (idSite)
TagManager.addContainer (idSite, context, name, description = '', ignoreGtmDataLayer = '0', isTagFireLimitAllowedInPreviewMode = '0', activelySyncGtmDataLayer = '0')
TagManager.updateContainer (idSite, idContainer, name, description = '', ignoreGtmDataLayer = '0', isTagFireLimitAllowedInPreviewMode = '0', activelySyncGtmDataLayer = '0')
TagManager.deleteContainer (idSite, idContainer)
```

## Tags

```
# Read
TagManager.getContainerTags (idSite, idContainer, idContainerVersion)
TagManager.getContainerTag (idSite, idContainer, idContainerVersion, idTag)

# Write
TagManager.addContainerTag (idSite, idContainer, idContainerVersion, type, name, parameters = 'Array', fireTriggerIds = 'Array', blockTriggerIds = 'Array', fireLimit = 'unlimited', fireDelay = '0', priority = '999', startDate = '', endDate = '', description = '', status = '')
TagManager.updateContainerTag (idSite, idContainer, idContainerVersion, idTag, name, parameters = 'Array', fireTriggerIds = 'Array', blockTriggerIds = 'Array', fireLimit = 'unlimited', fireDelay = '0', priority = '999', startDate = '', endDate = '', description = '')
TagManager.deleteContainerTag (idSite, idContainer, idContainerVersion, idTag)
TagManager.pauseContainerTag (idSite, idContainer, idContainerVersion, idTag)
TagManager.resumeContainerTag (idSite, idContainer, idContainerVersion, idTag)
```

## Triggers

```
# Read
TagManager.getContainerTriggers (idSite, idContainer, idContainerVersion)
TagManager.getContainerTrigger (idSite, idContainer, idContainerVersion, idTrigger)
TagManager.getContainerTriggerReferences (idSite, idContainer, idContainerVersion, idTrigger)

# Write
TagManager.addContainerTrigger (idSite, idContainer, idContainerVersion, type, name, parameters = 'Array', conditions = 'Array', description = '')
TagManager.updateContainerTrigger (idSite, idContainer, idContainerVersion, idTrigger, name, parameters = 'Array', conditions = 'Array', description = '')
TagManager.deleteContainerTrigger (idSite, idContainer, idContainerVersion, idTrigger)
```

## Variables

```
# Read
TagManager.getContainerVariables (idSite, idContainer, idContainerVersion)
TagManager.getContainerVariable (idSite, idContainer, idContainerVersion, idVariable)
TagManager.getContainerVariableReferences (idSite, idContainer, idContainerVersion, idVariable)
TagManager.getAvailableContainerVariables (idSite, idContainer, idContainerVersion)

# Write
TagManager.addContainerVariable (idSite, idContainer, idContainerVersion, type, name, parameters = 'Array', defaultValue = '', lookupTable = 'Array', description = '')
TagManager.updateContainerVariable (idSite, idContainer, idContainerVersion, idVariable, name, parameters = 'Array', defaultValue = '', lookupTable = 'Array', description = '')
TagManager.deleteContainerVariable (idSite, idContainer, idContainerVersion, idVariable)
```

## Versions

```
# Read
TagManager.getContainerVersions (idSite, idContainer)
TagManager.getContainerVersion (idSite, idContainer, idContainerVersion)

# Write
TagManager.createContainerVersion (idSite, idContainer, name, description = '', idContainerVersion = '')
TagManager.updateContainerVersion (idSite, idContainer, idContainerVersion, name, description = '')
TagManager.deleteContainerVersion (idSite, idContainer, idContainerVersion)
TagManager.publishContainerVersion (idSite, idContainer, idContainerVersion, environment)
```

## Preview / Debug

```
# Write
TagManager.enablePreviewMode (idSite, idContainer, idContainerVersion = '')
TagManager.disablePreviewMode (idSite, idContainer)
TagManager.changeDebugUrl (idSite, url)
```

## Import / Export

```
# Read
TagManager.exportContainerVersion (idSite, idContainer, idContainerVersion = '')

# Write
TagManager.importContainerVersion (exportedContainerVersion, idSite, idContainer, backupName = '')
```

## Permissions Required

- **Read methods** (`get*`, `export*`): `view` access to the site
- **Write methods** (`add*`, `update*`, `delete*`, `publish*`, `create*`, `pause*`, `resume*`, `enable*`, `disable*`, `change*`, `import*`): `admin` access to the site

## Usage from matometa

Read methods work with the existing `MatomoAPI.request()`:

```python
api.request("TagManager.getContainers", idSite=117)
api.request("TagManager.getContainerTags", idSite=117, idContainer="abc123", idContainerVersion=1)
```

Write methods require POST support (not yet implemented in `lib/_matomo.py`) and
an admin-level `token_auth`.
