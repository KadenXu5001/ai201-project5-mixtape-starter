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

My path was README -> routes/songs.py -> services/streak_service.py -> tests/test_streaks.py. In update_listening_streak, I found the exact condition that handles consecutive-day listens. The moment I was confident was when I saw that the increment branch only ran when days_since_last == 1 and today.weekday() != 6. Since Python returns 6 for Sunday, that meant Sunday was being excluded from normal consecutive-day streak behavior.

The root cause

The streak code treated Sunday as a special case even though the app’s rules say a streak should increment on any consecutive calendar day. In update_listening_streak, a user only got a streak increment when the previous listen was one day ago and today.weekday() was not 6. Because weekday() returns 6 for Sunday, a Saturday-to-Sunday listen fell into the reset branch instead of the increment branch.

Your fix and side-effect check

I removed the Sunday exclusion so the code now increments whenever days_since_last == 1. I also checked the surrounding logic to make sure the same-day case still does nothing and the skipped-day case still resets to 1.

Issue 3: The same song keeps showing up twice in search

How I reproduced it

I used the multi-tag scenario described in tests/test_search.py. The reproduction case is a song with multiple rows in the song_tags join table, then searching by that song's title or artist. The test data uses Crown Heights Anthem with three tags, which is exactly the kind of record that would show duplicate results.

How I found the root cause

My path was README -> routes/songs.py -> services/search_service.py -> tests/test_search.py. The songs route showed that search requests go straight to search_service.search_songs. In that function, I found a query that selects Song, outer joins to song_tags, and then filters on title or artist. The moment I was confident was when I compared that join against the test fixture that gives one song three tag rows. That means the query can return the same Song once for each matching join row.

The root cause

The search query was joining Song to song_tags without removing duplicate parent Song rows afterward. A song with multiple tags has multiple matching rows in the join table, so searching for that song could return the same song multiple times in the result list even though it is only one logical song.

Your fix and side-effect check

I added distinct() to the search query so the result set is collapsed back to unique Song rows after the join. That fixes the duplicate-result problem without changing the title or artist filtering behavior. I also checked the surrounding behavior against the existing tests: songs with one tag should still appear once, songs with no tags should still appear once because the query still uses an outer join, and non-matching searches should still return an empty list.
