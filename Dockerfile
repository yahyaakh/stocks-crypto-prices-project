
# The Dockerfile is designed for the production image. 
# It uses gunicorn, which is a production-grade WSGI server capable of handling concurrent requests efficiently.

# The docker-compose.yml is for my local development. 
#I override the command to use Django's built-in runserver because 
#it supports hot-reloading (auto-restart on code save) and creates a smoother debugging experience.



# Use an official Python runtime as a parent image
FROM python:3.11-slim

# I chose slim because it is much smaller (lighter) than the standard Python image, which speeds up deployment


# Set environment variables to prevent generating .pyc files and to run Python in unbuffered mode
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Set the working directory in the container
WORKDIR /app


# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install pip and system dependencies
RUN pip install --upgrade pip
RUN apt-get update && apt-get install -y \
    gcc \ 
    g++ \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

 # Some Python packages require compilation, so we need a C compiler for  gcc \  g++ \


# Install any needed packages specified in requirements.txt
RUN pip install -r requirements.txt

# Copy the rest of the project's files into the container at /app


# "In my Dockerfile,i copy requirements.txt and run pip install before copying the rest of your code (COPY . .)"

#The reason : This utilizes Docker Layer Caching. Docker caches every step. 
#If I change a line of code in views.py, only the layers after COPY . . need to be rebuilt. 
#If I put COPY . . first, Docker would reinstall all dependencies every time I changed a single line of code, 
#which would make builds very slow. By separating them, pip install only runs when I actually change requirements.txt."

COPY . .

WORKDIR /app/myproject



# The staticfiles_production folder is generated during the Docker Build stage. 
#It exists inside the immutable Docker Image layer to ensure consistency across environments. 
#It is not mirrored to my local filesystem to keeps the development environment clean.

RUN mkdir -p staticfiles_production
RUN python manage.py collectstatic --noinput


# I run collectstatic during the build phase to 'bake' the static assets (CSS, JS) directly into the Docker image 
#inside the staticfiles_production folder. 
#This makes the image self-contained. When I deploy this container to Azure, it already has all the files it needs. 
#I don't need to mount an external volume or run commands manually on the server after deployment."


# Expose the port the app runs on
EXPOSE 8000

# Specify the command to run on container start
CMD ["gunicorn", "--chdir", "myproject", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "myproject.wsgi:application"]