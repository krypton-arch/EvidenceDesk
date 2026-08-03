import json
import random

def generate_tweet(id_num):
    clusters = ["Politics", "Tech", "Entertainment", "Sports", "Noise"]
    cluster = random.choice(clusters)
    
    urls = []
    if random.random() > 0.5:
        urls.append(f"https://t.co/{random.randint(1000, 9999)}")
        
    return {
        "id": f"tweet_{id_num}",
        "text": f"This is a simulated tweet about {cluster} with random content {random.randint(0, 1000)}",
        "cluster": cluster,
        "urls": urls,
        "is_noise": cluster == "Noise"
    }

def main():
    dataset = [generate_tweet(i) for i in range(250)]
    with open("dataset.json", "w") as f:
        json.dump(dataset, f, indent=2)
    print("Generated dataset.json with 250 synthetic tweets.")

if __name__ == "__main__":
    main()
