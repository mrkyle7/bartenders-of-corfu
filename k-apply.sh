set -e

if ! docker network ls --format '{{.Name}}' | grep -qw k3s-net; then
  echo "Creating docker network k3s-net"
  docker network create k3s-net
fi

if ! docker ps --format '{{.Names}}' | grep -qw registry; then
  echo "Starting local docker registry"
  docker run --name registry -d -p 5000:5000 --network k3s-net --hostname docker-registry --restart=always registry:latest
fi

if ! docker ps --format '{{.Names}}' | grep -qw k3s-server; then
    echo "starting k3s-server container"
    docker run --privileged --name k3s-server -d \
    -p 6443:6443 -p 80:80 -p 443:443 -p 30080:30080 -p 9080:80\
    -v k3s-data:/var/lib/rancher/k3s \
    --hostname k3s-server \
    --network k3s-net \
    rancher/k3s:v1.29.1-k3s1 server \
    --node-name k3s-server 
fi 

TAG="$(date -u +%Y%m%d%H%M%S)-$(head -c4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
echo "Using image tag: $TAG"
docker build . -t localhost:5000/bartenders-464918/docker-us/bartenders:$TAG
docker push localhost:5000/bartenders-464918/docker-us/bartenders:$TAG
docker cp k3s-registries.yaml k3s-server:/etc/rancher/k3s/registries.yaml
docker cp k3s-server:/etc/rancher/k3s/k3s.yaml k3s.yaml
export KUBECONFIG=k3s.yaml
export IMAGE_TAG=$TAG ; envsubst < k3s/bartenders.yml > k3s-rendered/bartenders.rendered.yml
cp k3s/nginx.yml k3s-rendered/
kubectl apply -f k3s-rendered/ --prune -l app=bartenders
kubectl rollout status deployment/bartenders --timeout=120s

DEPLOYED_TAG="$(kubectl get pods -l app=bartenders -o=jsonpath='{$.items[0].spec.containers[0].image}' | cut -d : -f 2)"
echo "Deployed image tag: $DEPLOYED_TAG"
if [ "$DEPLOYED_TAG" != "$TAG" ]; then
  echo "Error: Deployed tag ($DEPLOYED_TAG) does not match expected tag ($TAG)"
else
  echo "Success: Deployed tag matches expected tag."
fi
kubectl get pods
sleep 2
kubectl logs -l app=bartenders --tail=20