import os
import re
import random
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
import requests

from helpers import login_required

API_URL = "https://www.freetogame.com/api/games"

# Configure application
app = Flask(__name__)

#edited here for Render
if __name__ == "__main__":
    from os import environ
    app.run(host="0.0.0.0", port=int(environ.get("PORT", 5000)))


# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///games.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/", defaults={'game_id': None})
@app.route("/<int:game_id>")
@login_required
def index(game_id):
    user = session["user_id"]

    query = request.args.get('name', '')  # get the game name from the query string
    platform = request.args.get('platform', '')  # get game platform
    category = request.args.get('category', '')  # get the game category
    sort = request.args.get('sort', '')  # get the game ordering
    page = int(request.args.get('page', 1))  # Default to page 1 if not specified

    # Build the API request URL based on the filters
    api_request_url = API_URL  # get all games to show in home page
    params = {}

    if platform:
        params['platform'] = platform
    if category:
        params['category'] = category
    if sort:
        params['sort-by'] = sort

    # get data from API
    response = requests.get(api_request_url, params=params)

    if response.status_code == 200:  # check games were recived sucsussfully
        games = response.json()

        # filter games by name if a query is provided
        if query:
            games = [game for game in games if query.lower() in game['title'].lower()]
    else:
        games = []

    # pagination
    games_per_page = 30
    total_pages = (len(games) + games_per_page - 1) // games_per_page
    start = (page - 1) * games_per_page
    end = start + games_per_page
    paginated_games = games[start:end]

    if game_id:
        # get game details using the game_id when user clicked on a game
        game_details_response = requests.get(f"https://www.freetogame.com/api/game?id={game_id}")
        if game_details_response.status_code == 200:
            game_details = game_details_response.json()
            # show game details in detailed.html
            return render_template('detailed.html', game=game_details)

    return render_template('index.html', games=paginated_games, current_page=page, total_pages=total_pages, query=query, platform=platform, category=category, sort=sort)


@app.route("/library")
@login_required
def library():
    """show liked games in library and show recomondations"""
    user_id = session["user_id"]

    # get user's liked games id from likes table
    liked_game_ids = db.execute("SELECT gameid FROM likes WHERE userid = ?", user_id)
    liked_games = []

    # get liked game details from the API for each
    if liked_game_ids:
        game_ids = [game["gameid"] for game in liked_game_ids]
        for game_id in game_ids:
            api_request_url = f"https://www.freetogame.com/api/game?id={game_id}"
            response = requests.get(api_request_url)
            game_data = response.json()
            liked_games.append(game_data)

    # Recommendation by user's liked games tags
    recommended_games = []
    # get user's liked games tags
    liked_game_tags = db.execute(
        "SELECT tag FROM liked_game_tags WHERE like_id IN (SELECT id FROM likes WHERE userid = ?)", user_id)
    if liked_game_tags:
        tag_counts = {}
        for tag_data in liked_game_tags:
            tag = tag_data["tag"]
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # get most liked 3 tags
        top_tags = sorted(tag_counts, key=tag_counts.get, reverse=True)[:3]

        # looping 3 times to get games for each tag catogory
        for tag in top_tags:
            api_url = f"https://www.freetogame.com/api/games?category={tag}"
            response = requests.get(api_url)
            if response.status_code == 200:
                games_by_tag = response.json()
                # Exclude already liked games
                games_by_tag = [game for game in games_by_tag if game["id"] not in [game["gameid"] for game in liked_game_ids] ]
                recommended_games.extend(games_by_tag)
        random.shuffle(recommended_games)
        recommended_games = recommended_games[:5]

    # show liked and recomonded games in library page
    return render_template("library.html", liked_games=liked_games, recommended_games=recommended_games)


@app.route("/like", methods=["POST"])
@login_required
def like():
    """like games"""
    user_id = session["user_id"]

    game_id = request.form.get("game_id")
    if not game_id:
        flash("Game ID not found.", "error")
        return redirect("/")

    try:
        # check whether game is exists or not
        existing_like = db.execute(
            "SELECT id FROM likes WHERE userid = ? AND gameid = ?", user_id, game_id)
        if existing_like:
            flash("Game already liked.", "error")
            return redirect("/")  # redirect back to previous page with errored message

        db.execute("INSERT INTO likes (userid, gameid) VALUES (?, ?)", user_id, game_id)
        like_id = db.execute("SELECT last_insert_rowid()")[
            0]["last_insert_rowid()"]  # Get the ID of the newly inserted like

        # get game details for id,tag
        api_request_url = f"https://www.freetogame.com/api/game?id={game_id}"
        response = requests.get(api_request_url)
        game_data = response.json()
        tags = game_data.get("genre", "").split(",")
        for tag in tags:
            tag = tag.strip()
            db.execute("INSERT INTO liked_game_tags (like_id, tag) VALUES (?, ?)",
                       like_id, tag)  # insert gameid and tag into liked_game_tags table

    except:
        flash("Unable to like game.", "error")
        return redirect("/")

    flash("Game liked successfully!", "success")
    return redirect("/")  # redirecting to home page


@app.route("/unlike", methods=["POST"])
@login_required
def unlike():
    """unlike games from library"""
    user_id = session["user_id"]

    game_id = request.form.get("game_id")
    if not game_id:
        flash("Game ID not found.", "error")
        return redirect("/library")  # Redirect to library page

    try:
        # deleting likes from likes_game_tages table that contains foriegn keys
        db.execute(
            "DELETE FROM liked_game_tags WHERE like_id IN (SELECT id FROM likes WHERE userid = ? AND gameid = ?)", user_id, game_id)

        # deleting likes from likes table
        db.execute("DELETE FROM likes WHERE userid = ? AND gameid = ?", user_id, game_id)

    except:
        flash("Unable to unlike game.", "error")
        return redirect("/library")  # redirect to library page

    flash("Game unliked successfully!", "success")
    return redirect("/library")  # redirect to library page


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # check for username
        if not request.form.get("username"):
            flash("Username is required.", "error")
            return render_template("login.html")

        # check for password
        elif not request.form.get("password"):
            flash("Password is required.", "error")
            return render_template("login.html")

        # get username form users table
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # check whether username exists and password correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            flash("Invalid username and/or password.", "error")
            return render_template("login.html")

        session["user_id"] = rows[0]["id"]

        flash("Log in successful!", "success")
        return redirect("/")  # if login success, redirecting to the home page

    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # forget any user_id
    session.clear()

    # redirecting to login page
    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        # check for username
        if not request.form.get("username"):
            flash("Username is required.", "error")
        # check for password
        elif not (request.form.get("password")):
            flash("Password is required.", "error")
        # check for passsword confirmation
        elif not (request.form.get("confirmation")):
            flash("Password confirmation is required.", "error")
        # check whether password and its confirmations are match or not
        elif not request.form.get("password") == request.form.get("confirmation"):
            flash("Passwords do not match.", "error")
        # check whether password contain any special characters or not
        elif not re.search("[!@#$%^&*()]", request.form.get("password")):
            flash("Password must contain special characters.", "error")
        # check whether password contain any digits or not
        elif not re.search("[0-9]", request.form.get("password")):
            flash("Password must contain digits.", "error")
        # check whether username contains any special characters or not
        elif re.search("[!@#$%^&*()]", request.form.get("username")):
            flash("Username only contain letters", "error")
        # check whether username have over 20 characters or not
        elif len(request.form.get("username")) > 20:
            flash("Username not acceptable.", "error")
        else:
            # get password and username and genarate hash
            password = request.form.get("password")
            username = request.form.get("username")
            hash = generate_password_hash(password)
            try:
                # insert username and genarated hash into user table
                db.execute("INSERT INTO users (username, hash) VALUES (?, ?)", username, hash)
                return redirect("/")  # redirecting to login page
            except:
                flash("Error occured please try again", "error")

        return render_template("register.html")
    else:
        return render_template("register.html")


@app.route("/changePassword", methods=["GET", "POST"])
@login_required
def changePassword():
    """Allow user to change password."""

    if request.method == "POST":
        # check for live password
        if not (request.form.get("current_password")):
            flash("Current password is required.", "error")
            return render_template("changePassword.html")
        # check for new password
        elif not (request.form.get("new_password")):
            flash("New password is required.", "error")
            return render_template("changePassword.html")
        # check for new password confirmation
        elif not (request.form.get("confirm_password")):
            flash("Password confirmation is required.", "error")
            return render_template("changePassword.html")
        # check whether live new password and confirmation match or not
        elif not request.form.get("new_password") == request.form.get("confirm_password"):
            flash("Passwords does not match.", "error")
            return render_template("changePassword.html")
        # check whether new password contain any special characters or not
        elif not re.search("[!@#$%^&*()]", request.form.get("new_password")):
            flash("Password must contain special characters.", "error")
            return render_template("changePassword.html")
        # check whether new password contain any digits or not
        elif not re.search("[0-9]", request.form.get("new_password")):
            flash("Password must contain digits.", "error")
            return render_template("changePassword.html")

        user_id = session["user_id"]
        # get live user's password hash from users table
        rows = db.execute("SELECT hash FROM users WHERE id = ?", user_id)
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        # verify current password
        if not rows or not check_password_hash(rows[0]["hash"], current_password):
            flash("Invalid current password.", "error")
            return render_template("changePassword.html")
        # generate hash for new password
        hashed_new_password = generate_password_hash(new_password)
        # update new password hash in users table
        db.execute("UPDATE users SET hash = ? WHERE id = ?", hashed_new_password, user_id)

        flash("Password changed successfully!", "success")
        return redirect("/")  # redirecting to home page

    else:
        return render_template("changePassword.html")


@app.route("/deleteaccount", methods=["GET", "POST"])
@login_required
def deleteaccount():
    """Allow user to delete their account"""

    if request.method == "POST":
        verify_password = request.form.get("verify_password")

        if not verify_password:
            flash("Current password is required.", "error")
            return render_template("delete.html")

        user_id = session["user_id"]
        rows = db.execute("SELECT hash FROM users WHERE id = ?", user_id)

        if not rows or not check_password_hash(rows[0]["hash"], verify_password):
            flash("Invalid current password.", "error")
            return render_template("delete.html")

        try:
            # delete data from liked_game_tags table that contain foriegn key from likes table
            db.execute(
                "DELETE FROM liked_game_tags WHERE like_id IN (SELECT id FROM likes WHERE userid = ?)", user_id)
            # delete data from likes games table that contain foriegn key from users table
            db.execute("DELETE FROM likes WHERE userid = ?", user_id)
            # delete from users table
            db.execute("DELETE FROM users WHERE id = ?", user_id)

            # after delete the account log out user
            session.clear()
            return redirect("/")  # redirecting to login page

        except Exception as e:
            flash(f"Error deleting account: {e}", "error")
            return render_template("delete.html")  # render delete.html again with a error message

    else:
        return render_template("delete.html")
