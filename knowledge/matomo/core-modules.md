# Core Matomo Modules

Full method signatures for the most commonly used analytics modules.

## VisitsSummary

```
VisitsSummary.get(idSite, period, date, segment = '', columns = '')
VisitsSummary.getVisits(idSite, period, date, segment = '')
VisitsSummary.getUniqueVisitors(idSite, period, date, segment = '')
VisitsSummary.getActions(idSite, period, date, segment = '')
VisitsSummary.getBounceCount(idSite, period, date, segment = '')
VisitsSummary.getMaxActions(idSite, period, date, segment = '')
VisitsSummary.getSumVisitsLength(idSite, period, date, segment = '')
```

## Actions

```
Actions.get(idSite, period, date, segment = '', columns = '')
Actions.getPageUrls(idSite, period, date, segment = '', expanded = '', idSubtable = '', depth = '', flat = '')
Actions.getPageUrlsFollowingSiteSearch(idSite, period, date, segment = '', expanded = '', idSubtable = '')
Actions.getPageTitlesFollowingSiteSearch(idSite, period, date, segment = '', expanded = '', idSubtable = '')
Actions.getEntryPageUrls(idSite, period, date, segment = '', expanded = '', idSubtable = '', flat = '')
Actions.getExitPageUrls(idSite, period, date, segment = '', expanded = '', idSubtable = '', flat = '')
Actions.getPageUrl(pageUrl, idSite, period, date, segment = '')
Actions.getPageTitles(idSite, period, date, segment = '', expanded = '', idSubtable = '', flat = '')
Actions.getEntryPageTitles(idSite, period, date, segment = '', expanded = '', idSubtable = '', flat = '')
Actions.getExitPageTitles(idSite, period, date, segment = '', expanded = '', idSubtable = '', flat = '')
Actions.getPageTitle(pageName, idSite, period, date, segment = '')
Actions.getDownloads(idSite, period, date, segment = '', expanded = '', idSubtable = '', flat = '')
Actions.getDownload(downloadUrl, idSite, period, date, segment = '')
Actions.getOutlinks(idSite, period, date, segment = '', expanded = '', idSubtable = '', flat = '')
Actions.getOutlink(outlinkUrl, idSite, period, date, segment = '')
Actions.getSiteSearchKeywords(idSite, period, date, segment = '')
Actions.getSiteSearchNoResultKeywords(idSite, period, date, segment = '')
Actions.getSiteSearchCategories(idSite, period, date, segment = '')
```

## CustomDimensions

```
CustomDimensions.getCustomDimension(idDimension, idSite, period, date, segment = '', expanded = '', flat = '', idSubtable = '')
CustomDimensions.getConfiguredCustomDimensions(idSite)
CustomDimensions.getConfiguredCustomDimensionsHavingScope(idSite, scope)
CustomDimensions.getAvailableScopes(idSite)
CustomDimensions.getAvailableExtractionDimensions()
CustomDimensions.configureNewCustomDimension(idSite, name, scope, active, extractions = 'Array', caseSensitive = '1')
CustomDimensions.configureExistingCustomDimension(idDimension, idSite, name, active, extractions = 'Array', caseSensitive = '')
```

## Events

```
Events.getCategory(idSite, period, date, segment = '', expanded = '', secondaryDimension = '', flat = '')
Events.getAction(idSite, period, date, segment = '', expanded = '', secondaryDimension = '', flat = '')
Events.getName(idSite, period, date, segment = '', expanded = '', secondaryDimension = '', flat = '')
Events.getActionFromCategoryId(idSite, period, date, idSubtable, segment = '')
Events.getNameFromCategoryId(idSite, period, date, idSubtable, segment = '')
Events.getCategoryFromActionId(idSite, period, date, idSubtable, segment = '')
Events.getNameFromActionId(idSite, period, date, idSubtable, segment = '')
Events.getActionFromNameId(idSite, period, date, idSubtable, segment = '')
Events.getCategoryFromNameId(idSite, period, date, idSubtable, segment = '')
```

**⚠️ CRITICAL: Segments filter VISITS, not EVENTS.** Using `segment=pageUrl=@/gps/`
returns events from visits that included a GPS page, NOT events triggered on GPS
pages. An event fired on `/dashboard/` will be included if the user later visited
`/gps/`. To find which events fire ON specific pages, search the codebase for
`matomo_event` or `data-matomo-*` and check which templates contain them. See
`skills/sync-events/SKILL.md` for the full methodology.

## Referrers

```
Referrers.get(idSite, period, date, segment = '', columns = '')
Referrers.getReferrerType(idSite, period, date, segment = '', typeReferrer = '', idSubtable = '', expanded = '')
Referrers.getAll(idSite, period, date, segment = '')
Referrers.getKeywords(idSite, period, date, segment = '', expanded = '', flat = '')
Referrers.getSearchEnginesFromKeywordId(idSite, period, date, idSubtable, segment = '')
Referrers.getSearchEngines(idSite, period, date, segment = '', expanded = '', flat = '')
Referrers.getKeywordsFromSearchEngineId(idSite, period, date, idSubtable, segment = '')
Referrers.getCampaigns(idSite, period, date, segment = '', expanded = '')
Referrers.getKeywordsFromCampaignId(idSite, period, date, idSubtable, segment = '')
Referrers.getWebsites(idSite, period, date, segment = '', expanded = '', flat = '')
Referrers.getUrlsFromWebsiteId(idSite, period, date, idSubtable, segment = '')
Referrers.getSocials(idSite, period, date, segment = '', expanded = '', flat = '')
Referrers.getUrlsForSocial(idSite, period, date, segment = '', idSubtable = '')
Referrers.getNumberOfDistinctSearchEngines(idSite, period, date, segment = '')
Referrers.getNumberOfDistinctSocialNetworks(idSite, period, date, segment = '')
Referrers.getNumberOfDistinctKeywords(idSite, period, date, segment = '')
Referrers.getNumberOfDistinctCampaigns(idSite, period, date, segment = '')
Referrers.getNumberOfDistinctWebsites(idSite, period, date, segment = '')
Referrers.getNumberOfDistinctWebsitesUrls(idSite, period, date, segment = '')
```

## VisitFrequency

```
VisitFrequency.get(idSite, period, date, segment = '', columns = '')
```

Returns metrics prefixed by visitor type: `nb_visits_returning`, `nb_visits_new`, etc.

## Live

```
Live.getCounters(idSite, lastMinutes, segment = '', showColumns = 'Array', hideColumns = 'Array')
Live.getLastVisitsDetails(idSite, period = '', date = '', segment = '', countVisitorsToFetch = '', minTimestamp = '', flat = '', doNotFetchActions = '', enhanced = '')
Live.getVisitorProfile(idSite, visitorId = '', segment = '', limitVisits = '')
Live.getMostRecentVisitorId(idSite, segment = '')
```

## Goals

```
Goals.get(idSite, period, date, segment = '', idGoal = '', columns = 'Array', showAllGoalSpecificMetrics = '', compare = '')
Goals.getGoals(idSite)
Goals.getGoal(idSite, idGoal)
Goals.getDaysToConversion(idSite, period, date, segment = '', idGoal = '')
Goals.getVisitsUntilConversion(idSite, period, date, segment = '', idGoal = '')
Goals.getItemsSku(idSite, period, date, abandonedCarts = '', segment = '')
Goals.getItemsName(idSite, period, date, abandonedCarts = '', segment = '')
Goals.getItemsCategory(idSite, period, date, abandonedCarts = '', segment = '')
Goals.addGoal(idSite, name, matchAttribute, pattern, patternType, caseSensitive = '', revenue = '', allowMultipleConversionsPerVisit = '', description = '', useEventValueAsRevenue = '')
Goals.updateGoal(idSite, idGoal, name, matchAttribute, pattern, patternType, caseSensitive = '', revenue = '', allowMultipleConversionsPerVisit = '', description = '', useEventValueAsRevenue = '')
Goals.deleteGoal(idSite, idGoal)
```

## Transitions

```
Transitions.getTransitionsForPageUrl(pageUrl, idSite, period, date, segment = '', limitBeforeGrouping = '0')
Transitions.getTransitionsForPageTitle(pageTitle, idSite, period, date, segment = '', limitBeforeGrouping = '0')
Transitions.getTransitionsForAction(actionName, actionType, idSite, period, date, segment = '', limitBeforeGrouping = '0', parts = 'all')
Transitions.getTranslations()
Transitions.isPeriodAllowed(idSite, period, date)
```

## VisitTime

```
VisitTime.getVisitInformationPerLocalTime(idSite, period, date, segment = '')
VisitTime.getVisitInformationPerServerTime(idSite, period, date, segment = '')
VisitTime.getByDayOfWeek(idSite, period, date, segment = '')
```

## DevicesDetection

```
DevicesDetection.getType(idSite, period, date, segment = '')
DevicesDetection.getBrand(idSite, period, date, segment = '')
DevicesDetection.getModel(idSite, period, date, segment = '')
DevicesDetection.getOsFamilies(idSite, period, date, segment = '')
DevicesDetection.getOsVersions(idSite, period, date, segment = '')
DevicesDetection.getBrowsers(idSite, period, date, segment = '')
DevicesDetection.getBrowserVersions(idSite, period, date, segment = '')
DevicesDetection.getBrowserEngines(idSite, period, date, segment = '')
```

## Resolution

```
Resolution.getResolution(idSite, period, date, segment = '')
Resolution.getConfiguration(idSite, period, date, segment = '')
```

Returns screen resolutions (e.g., "1920x1080", "390x844") with visit metrics. Useful for:
- Identifying desktop vs mobile usage patterns
- Detecting device fragmentation by user segment
- UX/design decisions (breakpoints, mobile-first priorities)

**Segmentation tip:** Combine with custom dimensions to analyze by user type:
`segment=dimension1==job_seeker` reveals mobile-heavy audiences vs desktop-heavy ones.

## UserCountry

```
UserCountry.getCountry(idSite, period, date, segment = '')
UserCountry.getContinent(idSite, period, date, segment = '')
UserCountry.getRegion(idSite, period, date, segment = '')
UserCountry.getCity(idSite, period, date, segment = '')
UserCountry.getCountryCodeMapping()
```

## VisitorInterest

```
VisitorInterest.getNumberOfVisitsPerVisitDuration(idSite, period, date, segment = '')
VisitorInterest.getNumberOfVisitsPerPage(idSite, period, date, segment = '')
VisitorInterest.getNumberOfVisitsByDaysSinceLast(idSite, period, date, segment = '')
VisitorInterest.getNumberOfVisitsByVisitCount(idSite, period, date, segment = '')
```
