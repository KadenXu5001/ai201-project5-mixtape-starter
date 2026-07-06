# Mixtape Codebase Map

High-level structure

This repo is a small Flask API organized into routing, business logic, and database models.

- app.py builds the Flask app, configures SQLAlchemy, registers blueprints, and creates tables on startup.
- models.py defines the database schema and relationships between users, songs, playlists, listening events, ratings, tags, and notifications.
- routes/ contains thin Flask blueprints. The route handlers mostly parse request data, call one service function, and return JSON.
- services/ contains the business logic. This is where the app decides how to search songs, update streaks, build feeds, create playlists, and create notifications.
- tests/ checks service-layer behavior with an in-memory SQLite database.
- seed_data.py resets and repopulates the database with realistic sample data.

The app is API-only right now. There is no homepage route at /. The main entry points are JSON endpoints under /songs, /playlists, /users, and /feed.

Main files and what they do

app.py

app.py is the application factory. The create_app function:

- creates the Flask app
- loads config values like the database URL
- initializes the database object
- imports and registers blueprints from routes/
- calls db.create_all() inside the app context

This file wires the whole app together, but it does not contain much product logic itself.

models.py

models.py is the core mental model for the app. It defines:

- User: stores identity plus listening streak state
- Song: stores shared music metadata and who shared it
- Tag: reusable labels attached to songs
- ListeningEvent: one row per listen action
- Rating: one row per user/song score, with a uniqueness constraint so a user can only have one rating per song
- Playlist: playlist metadata
- Notification: user-facing alerts

It also defines three association tables:

- friendships: a symmetric many-to-many relationship between users
- song_tags: a many-to-many relationship between songs and tags
- playlist_entries: a many-to-many relationship between playlists and songs, but with extra columns like position, added_by, and added_at

The important pattern here is that playlist_entries is not just a join table. It carries ordering and audit information, so playlist membership has extra metadata attached to it.

routes/songs.py

This blueprint handles song-related actions:

- GET /songs/search?q=... calls search_service.search_songs()
- GET /songs/<song_id> calls search_service.get_song()
- POST /songs/<song_id>/rate calls notification_service.rate_song()
- POST /songs/<song_id>/listen calls streak_service.record_listening_event()

This file shows the overall route style of the app well: validate basic request inputs, call a service, then serialize the result.

routes/playlists.py

This blueprint handles playlist creation and song membership:

- POST /playlists/ calls playlist_service.create_playlist()
- GET /playlists/<playlist_id> calls playlist_service.get_playlist()
- GET /playlists/<playlist_id>/songs calls playlist_service.get_playlist_songs()
- POST /playlists/<playlist_id>/songs calls notification_service.add_to_playlist()

One interesting design detail is that adding a song to a playlist is routed to notification_service, not playlist_service, because the action has both a playlist update and a notification side effect.

routes/users.py

This blueprint exposes user-facing read operations:

- GET /users/<user_id> returns the User record directly from the database
- GET /users/<user_id>/streak calls streak_service.get_streak()
- GET /users/<user_id>/notifications calls notification_service.get_notifications()
- POST /users/notifications/<notification_id>/read calls notification_service.mark_as_read()

This file mixes direct model access and service calls. The simplest read, get_user, bypasses a service layer entirely, while stateful or derived behaviors use services.

routes/feed.py

This blueprint exposes social feed endpoints:

- GET /feed/<user_id>/listening-now calls feed_service.get_friends_listening_now()
- GET /feed/<user_id>/activity calls feed_service.get_activity_feed()

These are read-only endpoints built from ListeningEvent history plus the friendship graph.

services/search_service.py

This module handles song lookup:

- search_songs(query) performs a case-insensitive title or artist match and returns song dictionaries
- get_song(song_id) fetches one song or raises a ValueError

It joins against song_tags, which makes sense because Song.to_dict() includes tag names.

services/streak_service.py

This module owns listen recording and streak updates:

- record_listening_event(user_id, song_id) creates a ListeningEvent, updates the user's streak state, commits, and returns the event
- update_listening_streak(user, now) contains the calendar-day streak rules
- get_streak(user_id) returns the stored streak counter

This is a good example of stateful business logic living outside the route layer.

services/feed_service.py

This module builds social feeds from friendship and listening history:

- get_friends_listening_now(user_id) finds recent listening events from the user's friends and collapses them to one latest event per friend
- get_activity_feed(user_id, limit=20) returns the most recent events from friends without the recency filter

This service is query-oriented. It does not mutate data. It assembles response objects from existing rows.

services/playlist_service.py

This module owns playlist creation and retrieval:

- create_playlist(...) validates the creator and inserts a Playlist
- get_playlist_songs(playlist_id) loads playlist songs ordered by playlist_entries.position
- get_playlist(playlist_id) returns playlist metadata only
- get_user_playlists(user_id) returns playlists created by one user

The important detail is that playlist order comes from the position column in playlist_entries, not from insertion order in the ORM relationship.

services/notification_service.py

This module is the most cross-cutting service in the repo. It handles:

- create_notification(...)
- add_to_playlist(...)
- rate_song(...)
- get_notifications(...)
- mark_as_read(...)

It mixes pure notification logic with other social interactions. In practice, it acts like an interaction side-effects service because it owns things that may create alerts in response to user actions.

seed_data.py

This script rebuilds the database and inserts realistic demo data:

- users with bidirectional friendships
- songs with varying tag counts
- playlists with positioned songs
- recent and older listening events
- some existing streak-related timestamps
- an example notification

This file is useful because it encodes the domain assumptions the app expects. Social graph, listening history, playlist ordering, and tagged songs all matter to the product.

tests/

The tests reveal what the app considers important behavior:

- test_search.py checks search correctness and duplicate handling
- test_playlists.py checks playlist completeness and ordering
- test_streaks.py checks consecutive-day streak rules

The pattern here is that tests target service functions directly. That reinforces the idea that the service layer is the main behavior surface of the app.

Data flow trace: adding a song to a playlist triggers a notification

This is one of the clearest cross-file flows in the app.

1. A client sends POST /playlists/<playlist_id>/songs with JSON containing song_id and added_by.
2. In routes/playlists.py, add_song() validates those two fields and calls notification_service.add_to_playlist(playlist_id, song_id, added_by).
3. In services/notification_service.py, add_to_playlist() loads the Song, the user who added it, and the Playlist.
4. If the song is not already in playlist.songs, it appends the Song to the playlist relationship and commits.
5. After the playlist update, the service checks whether the adder is different from the original sharer.
6. If so, it calls create_notification(...).
7. create_notification() inserts a Notification row for the original sharer with type song_added_to_playlist and a human-readable message.
8. The route returns a success message with status 201.

What this trace shows:

- routes are thin wrappers
- service functions often both validate domain state and mutate the database
- notifications are stored as first-class rows, not derived at read time
- one user action can touch multiple tables

Data flow trace: listening to a song updates streaks and later powers feeds

Another useful end-to-end flow is the listen action.

1. A client sends POST /songs/<song_id>/listen with user_id.
2. routes/songs.py calls streak_service.record_listening_event(user_id, song_id).
3. record_listening_event() creates a ListeningEvent with the current UTC timestamp.
4. It then calls update_listening_streak(user, now) before committing.
5. update_listening_streak() compares the current date with user.last_listened_at and either starts the streak, leaves it unchanged for a second listen on the same day, increments it for a consecutive day, or resets it if a day was skipped.
6. After commit, the route returns the event as JSON.
7. Later, feed_service.get_friends_listening_now() and feed_service.get_activity_feed() read those ListeningEvent rows to build social feed responses for friends.

This is a nice example of one write path supporting multiple read features later.

Patterns I noticed

- The app follows a route/service/model layering style. Routes are intentionally thin, services hold most logic, and models are mostly persistence plus serialization.
- The service layer is the real center of behavior. That is why the tests target services directly and why the README tells you to trace from routes into services.
- Models commonly expose to_dict() methods, so services and routes return plain JSON-ready dictionaries instead of using a separate schema layer.
- Time-sensitive features consistently use UTC datetimes and compare timestamps in service code.
- Many social features are built from simple primitives:
  - friendships define who counts as a friend
  - listening events define activity
  - notifications define user-facing alerts
  - association tables define many-to-many relationships with extra metadata
- The repo is small, but responsibilities are already somewhat split by domain:
  - search and song lookup
  - streak tracking
  - feeds
  - playlists
  - notifications and interactions

Mental model summary

Mixtape is an API-first social music app built around a few core records: users, songs, listening events, playlists, ratings, and notifications. The routes expose these behaviors over JSON, but almost all meaningful rules live in services. If I were debugging a user-facing issue, I would start at the route to confirm the request path, then trace immediately into the service it calls, then check the corresponding model relationships and tests to understand the intended behavior.
