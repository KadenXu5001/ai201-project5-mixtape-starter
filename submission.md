Mixtape Codebase Map

Overview

This project is a small Flask API. The code is organized into app setup, models, routes, services, tests, and seed data. The routes are mostly thin and the service layer holds most of the behavior.

Main files and roles

- app.py creates the Flask app, loads config, initializes the database, registers the route blueprints, and creates tables.
- models.py defines the main data model: User, Song, Tag, ListeningEvent, Rating, Playlist, and Notification.
- models.py also defines the join tables. friendships connects users to friends, song_tags connects songs to tags, and playlist_entries connects playlists to songs while also storing position, who added the song, and when.
- routes/songs.py handles song search, single-song lookup, rating a song, and recording a listen.
- routes/playlists.py handles creating playlists, viewing playlist info, viewing playlist songs, and adding songs to a playlist.
- routes/users.py handles user lookup, streak lookup, notification lookup, and marking a notification as read.
- routes/feed.py handles the social feed endpoints for listening now and recent activity.
- services/search_service.py handles song search and getting a song by id.
- services/streak_service.py handles recording listening events and updating the user’s listening streak.
- services/feed_service.py builds the listening-now feed and the activity feed from friendship and listening history.
- services/playlist_service.py handles playlist creation and playlist retrieval, especially loading songs in playlist order.
- services/notification_service.py handles creating notifications, rating songs, adding songs to playlists, reading notifications, and marking notifications as read.
- seed_data.py rebuilds the database and fills it with sample users, friendships, songs, tags, playlists, listening events, and notifications.
- tests/test_search.py checks search behavior, tests/test_playlists.py checks playlist retrieval, and tests/test_streaks.py checks streak behavior.

How the app is organized

The overall pattern is route -> service -> model/database.

- Routes do request parsing and response formatting.
- Services do the main business logic.
- Models store the data and define relationships.

One thing I noticed is that the app is API-only right now. There is no homepage route at /. Everything is exposed through JSON endpoints like /songs, /playlists, /users, and /feed.

Data flow example: adding a song to a playlist triggers a notification

1. A client sends POST /playlists/<playlist_id>/songs with song_id and added_by.
2. routes/playlists.py validates the input and calls notification_service.add_to_playlist.
3. That service loads the Song, the User who added it, and the Playlist.
4. If the song is not already in the playlist, it appends the song to playlist.songs and commits.
5. Then it checks whether the person adding the song is different from the person who originally shared it.
6. If they are different, it calls create_notification.
7. create_notification inserts a Notification row for the original sharer.
8. The route returns a success response.

This flow shows that one user action can touch more than one part of the app: the playlist relationship is updated first, then a notification is created as a side effect.

Other patterns I noticed

- The service layer is the center of the app’s behavior. The README and tests both point you toward tracing behavior through services.
- Many models have to_dict methods, so services and routes usually return plain dictionaries that are easy to turn into JSON.
- Time-based features use UTC timestamps, especially in listening events, feeds, and streak updates.
- playlist_entries is an important table because playlist songs are ordered by a stored position value, not just by insertion order.
- ListeningEvent is also important because it supports more than one feature: it updates streaks when a listen is recorded, and it is later reused to build the friend feed.

Summary

My main mental model is that Mixtape is a social music app built around a few core records: users, songs, listening events, playlists, ratings, and notifications. If I wanted to understand any feature, I would start at the route, trace into the service it calls, and then look at the models and tests that support that behavior.

Root Cause Analysis

Issue 1: My listening streak keeps resetting

How I reproduced it

I looked at the streak tests first and used the Saturday-to-Sunday case in tests/test_streaks.py as the reproduction path. The triggering condition was a user listening on Saturday and then again on Sunday. That sequence should keep the streak going, but the code path would reset it instead of incrementing it.

How I found the root cause

My path was README -> routes/songs.py -> services/streak_service.py -> tests/test_streaks.py. In update_listening_streak, I found the exact condition that handles consecutive-day listens. I knew this was the cause when I saw that the increment branch only ran when days_since_last == 1 and today.weekday() != 6. Since Python returns 6 for Sunday, that meant Sunday was being excluded from normal consecutive-day streak behavior.

The root cause

The streak code treated Sunday as a special case even though the app’s rules say a streak should increment on any consecutive calendar day. In update_listening_streak, a user only got a streak increment when the previous listen was one day ago and today.weekday() was not 6. Because weekday() returns 6 for Sunday, a Saturday-to-Sunday listen fell into the reset branch instead of the increment branch.

Your fix and side-effect check

I removed the Sunday exclusion so the code now increments whenever days_since_last == 1. I also checked the surrounding logic to make sure the same-day case still does nothing and the skipped-day case still resets to 1.

Issue 2: Friends Listening Now shows people from yesterday

How I reproduced it

I traced this through the feed behavior and the seed data. In seed_data.py, the comments say that events within the past 30 minutes should appear in listening now, while older events should not. In services/feed_service.py, the current filter included any friend event from the last 24 hours. That means a friend who listened a few hours ago, or late yesterday if it was still within 24 hours, would still show up in a feed that is supposed to represent who is listening now.

How I found the root cause

My path was README -> routes/feed.py -> services/feed_service.py -> seed_data.py. The feed route showed that the listening-now endpoint goes straight to get_friends_listening_now. In that function, I found the cutoff based on RECENT_THRESHOLD. I knew this was the cause when I compared RECENT_THRESHOLD = timedelta(hours=24) against the seed data comment that defines listening now as the past 30 minutes. That was the exact mismatch controlling which rows qualified for the feed.

The root cause

The listening-now query was using a 24-hour recency window instead of a much shorter currently-listening window. Because ListeningEvent.listened_at only had to be newer than now minus 24 hours, the feed included stale events that were recent in a day-scale sense but not recent enough to count as listening now.

Your fix and side-effect check

I changed RECENT_THRESHOLD from 24 hours to 30 minutes so the filter matches the intended behavior described by the app's own seed data. I also added targeted tests in tests/test_feed.py to check two related behaviors after the change: first, that old friend events are excluded while recent friend events are still included, and second, that the feed still returns only the most recent song per friend when a friend has multiple recent listens.

Issue 3: The same song keeps showing up twice in search

How I reproduced it

I used the multi-tag scenario described in tests/test_search.py. The reproduction case is a song with multiple rows in the song_tags join table, then searching by that song's title or artist. The test data uses Crown Heights Anthem with three tags, which is exactly the kind of record that would show duplicate results.

How I found the root cause

My path was README -> routes/songs.py -> services/search_service.py -> tests/test_search.py. The songs route showed that search requests go straight to search_service.search_songs. In that function, I found a query that selects Song, outer joins to song_tags, and then filters on title or artist. I knew this was the cause when I compared that join against the test fixture that gives one song three tag rows. That means the query can return the same Song once for each matching join row.

The root cause

The search query was joining Song to song_tags without removing duplicate parent Song rows afterward. A song with multiple tags has multiple matching rows in the join table, so searching for that song could return the same song multiple times in the result list even though it is only one logical song.

Your fix and side-effect check

I added distinct() to the search query so the result set is collapsed back to unique Song rows after the join. That fixes the duplicate-result problem without changing the title or artist filtering behavior. I also checked the surrounding behavior against the existing tests: songs with one tag should still appear once, songs with no tags should still appear once because the query still uses an outer join, and non-matching searches should still return an empty list.

Issue 4: I got notified when a friend added my song to a playlist but not when they rated it

How I reproduced it

I traced the two interaction paths side by side. The playlist-add flow already created a notification for the song sharer, but the rating flow only saved the Rating row. The simplest reproduction case was a user rating a song that was shared by someone else and then checking whether a Notification row was created for the sharer.

How I found the root cause

My path was README -> routes/songs.py -> services/notification_service.py. The songs route showed that rating a song goes through rate_song. In notification_service.py, I compared rate_song with add_to_playlist. add_to_playlist calls create_notification after it updates the playlist, but rate_song ended right after db.session.commit() and returned the rating.

The root cause

The rating flow never created a notification. rate_song validated the user, song, and score, then created or updated the Rating and committed it, but it did not call create_notification for the song sharer. Because that step was missing entirely, rating a song could never produce the notification that the playlist-add flow already produced.

Your fix and side-effect check

I added a notification step to rate_song after the rating is saved. If the rater is not the same person as the song sharer, the service now creates a song_rated notification with the rater's username, the song title, and the score. I also added targeted tests in tests/test_notifications.py to check two related behaviors: first, that rating someone else's song creates exactly one notification for the sharer, and second, that rating your own song does not create a self-notification.

Issue 5: The last song in a playlist never shows up

How I reproduced it

I used the playlist test setup in tests/test_playlists.py. The reproduction case is a playlist with five songs inserted in order. When get_playlist_songs is called for that playlist, the expected result is all five songs in order, but the bug makes the returned list stop at the fourth song.

How I found the root cause

My path was README -> routes/playlists.py -> services/playlist_service.py -> tests/test_playlists.py. The playlists route showed that the endpoint goes straight to get_playlist_songs. In that function, the query itself looked fine: it joins through playlist_entries, filters by playlist_id, and orders by position. I knew this was the cause when I got to the return line and saw songs[:-1]. That slice removes the last element from the list every time, even when the query already returned the correct rows.

The root cause

The service was slicing off the final song before returning the result. In Python, songs[:-1] means "all items except the last one." Because get_playlist_songs returned [song.to_dict() for song in songs[:-1]], every non-empty playlist lost its final song even though the database query had already fetched it.

Your fix and side-effect check

I changed the return statement to use the full songs list instead of songs[:-1]. That fixes the missing-last-song bug without changing the ordering logic or the empty-playlist behavior. I also checked the existing tests around this function: one test expects all five songs to be returned, one checks that the order stays Track 1 through Track 5, and one checks that an empty playlist still returns an empty list.
