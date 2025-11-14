# frontend/Dockerfile
FROM --platform=linux/amd64 node:20

WORKDIR /usr/src/app

COPY package.json package-lock.json* ./

# Force clean install with specific flags
RUN npm ci --force --legacy-peer-deps || npm install --force --legacy-peer-deps

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]